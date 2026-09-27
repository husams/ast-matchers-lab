#include "matcher_engine.h"

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <filesystem>
#include <memory>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "compiler_config.h"
#include "clang/AST/ASTContext.h"
#include "clang/AST/ASTTypeTraits.h"
#include "clang/AST/Decl.h"
#include "clang/AST/DeclCXX.h"
#include "clang/AST/PrettyPrinter.h"
#include "clang/ASTMatchers/ASTMatchFinder.h"
#include "clang/ASTMatchers/Dynamic/Diagnostics.h"
#include "clang/ASTMatchers/Dynamic/Parser.h"
#include "clang/Basic/Diagnostic.h"
#include "clang/Basic/SourceManager.h"
#include "clang/Lex/Lexer.h"
#include "clang/Tooling/CompilationDatabase.h"
#include "clang/Tooling/Tooling.h"
#include "llvm/ADT/StringRef.h"
#include "llvm/Support/raw_ostream.h"

namespace astmatcher::native {
namespace {

namespace fs = std::filesystem;
namespace am = clang::ast_matchers;
namespace dynamic = clang::ast_matchers::dynamic;

constexpr uint32_t kDefaultMaxMatches = 1000;
constexpr uint32_t kMaximumMaxMatches = 10000;
constexpr size_t kMaximumTextBytes = 4096;
constexpr size_t kMaximumDiagnosticBytes = 64 * 1024;
constexpr std::string_view kDiagnosticTruncationMarker =
    "\n[Clang diagnostics truncated]\n";

void add_diagnostic(v1::RunReply &reply, uint32_t command_index,
                    const std::string &message, uint32_t line = 0,
                    uint32_t column = 0) {
  auto *diagnostic = reply.add_diagnostics();
  diagnostic->set_command_index(command_index);
  diagnostic->set_message(message);
  diagnostic->set_line(line);
  diagnostic->set_column(column);
}

std::string trim(llvm::StringRef text) { return text.trim().str(); }

bool valid_identifier(std::string_view name) {
  if (name.empty() ||
      !(std::isalpha(static_cast<unsigned char>(name.front())) ||
        name.front() == '_')) {
    return false;
  }
  return std::all_of(name.begin() + 1, name.end(), [](unsigned char character) {
    return std::isalnum(character) || character == '_';
  });
}

std::optional<clang::TraversalKind> parse_traversal(llvm::StringRef value) {
  if (value == "AsIs") {
    return clang::TK_AsIs;
  }
  if (value == "IgnoreUnlessSpelledInSource") {
    return clang::TK_IgnoreUnlessSpelledInSource;
  }
  return std::nullopt;
}

std::optional<bool> parse_bool(llvm::StringRef value) {
  if (value == "true" || value == "on" || value == "1") {
    return true;
  }
  if (value == "false" || value == "off" || value == "0") {
    return false;
  }
  return std::nullopt;
}

std::string parser_message(const dynamic::Diagnostics &diagnostics) {
  std::string message = diagnostics.toString();
  if (message.empty()) {
    return "Invalid matcher expression";
  }
  // The parser's text includes the position, which is also sent separately.
  return message;
}

std::pair<uint32_t, uint32_t>
parser_position(const dynamic::Diagnostics &diagnostics) {
  for (const auto &error : diagnostics.errors()) {
    for (const auto &message : error.Messages) {
      if (message.Range.Start.Line != 0) {
        return {message.Range.Start.Line - 1,
                message.Range.Start.Column ? message.Range.Start.Column - 1
                                           : 0};
      }
    }
  }
  return {0, 0};
}

std::string shortened(llvm::StringRef value, size_t limit) {
  if (value.size() <= limit) {
    return value.str();
  }
  return value.take_front(limit).str() + "…";
}

// Clang's source columns are byte offsets. VS Code/LSP columns count UTF-16
// code units, so convert each prefix before serializing a location.
uint32_t utf16_column(const clang::SourceManager &manager,
                      clang::SourceLocation location) {
  auto file = manager.getFileID(location);
  bool invalid = false;
  const llvm::StringRef buffer = manager.getBufferData(file, &invalid);
  if (invalid) {
    return manager.getSpellingColumnNumber(location) - 1;
  }
  const unsigned offset = manager.getFileOffset(location);
  size_t start = offset;
  while (start > 0 && buffer[start - 1] != '\n') {
    --start;
  }
  uint32_t units = 0;
  for (size_t i = start; i < offset;) {
    const unsigned char first = static_cast<unsigned char>(buffer[i]);
    size_t width = 1;
    if ((first & 0xE0) == 0xC0) {
      width = 2;
    } else if ((first & 0xF0) == 0xE0) {
      width = 3;
    } else if ((first & 0xF8) == 0xF0) {
      width = 4;
    }
    if (i + width > offset) {
      width = 1;
    }
    units += width == 4 ? 2 : 1;
    i += width;
  }
  return units;
}

void set_position(v1::Position *position, const clang::SourceManager &manager,
                  clang::SourceLocation location) {
  position->set_line(manager.getSpellingLineNumber(location) - 1);
  position->set_character(utf16_column(manager, location));
}

std::string semantic_kind(const clang::DynTypedNode &node) {
  const llvm::StringRef kind = node.getNodeKind().asStringRef();
  if (kind == "CXXRecordDecl" || kind == "RecordDecl") {
    if (const auto *record = node.get<clang::RecordDecl>()) {
      return record->isClass()    ? "class"
             : record->isStruct() ? "struct"
                                  : "union";
    }
    return "record";
  }
  if (kind == "EnumDecl") {
    return "enum";
  }
  if (kind == "EnumConstantDecl") {
    return "enum constant";
  }
  if (kind == "CXXConstructorDecl") {
    return "constructor";
  }
  if (kind == "CXXDestructorDecl") {
    return "destructor";
  }
  if (kind == "CXXConversionDecl") {
    return "conversion function";
  }
  if (kind == "CXXMethodDecl") {
    return "method";
  }
  if (kind == "FunctionDecl") {
    return "function";
  }
  if (kind == "ParmVarDecl") {
    return "parameter";
  }
  if (kind == "FieldDecl") {
    return "field";
  }
  if (kind == "BindingDecl") {
    return "binding";
  }
  if (kind == "VarDecl") {
    return "variable";
  }
  if (kind == "TypedefDecl" || kind == "TypeAliasDecl" ||
      kind == "TypeAliasTemplateDecl") {
    return "type alias";
  }
  if (kind == "NamespaceDecl" || kind == "NamespaceAliasDecl") {
    return "namespace";
  }
  if (kind.starts_with("ClassTemplate") ||
      kind.starts_with("TemplateTypeParm")) {
    return "template";
  }
  if (kind.ends_with("Decl")) {
    return "declaration";
  }
  return "";
}

std::string summary(const clang::DynTypedNode &node,
                    const clang::ASTContext &context,
                    llvm::StringRef source_text) {
  if (const auto *named = node.get<clang::NamedDecl>()) {
    if (const auto *value = llvm::dyn_cast<clang::ValueDecl>(named)) {
      return shortened(named->getNameAsString() + " '" +
                           value->getType().getAsString() + "'",
                       200);
    }
    return shortened(named->getNameAsString(), 200);
  }
  if (const auto *type = node.get<clang::QualType>()) {
    return shortened(type->getAsString(), 200);
  }
  if (!source_text.empty()) {
    const auto first_line = source_text.split('\n').first;
    return shortened(first_line.trim(), 200);
  }
  std::string printed;
  llvm::raw_string_ostream stream(printed);
  node.print(stream, context.getPrintingPolicy());
  stream.flush();
  return shortened(printed, 200);
}

std::string node_identity(const clang::DynTypedNode &node,
                          const v1::Binding &binding) {
  const void *pointer = node.getMemoizationData();
  if (!pointer) {
    if (const auto *type = node.get<clang::QualType>()) {
      pointer = type->getAsOpaquePtr();
    } else if (const auto *type_location = node.get<clang::TypeLoc>()) {
      pointer = type_location->getOpaqueData();
    }
  }
  if (pointer) {
    std::ostringstream stream;
    stream << pointer;
    return stream.str();
  }
  std::ostringstream stream;
  stream << binding.kind() << ':' << binding.range().file() << ':'
         << binding.range().start().line() << ':'
         << binding.range().start().character() << ':' << binding.summary();
  return stream.str();
}

void fill_binding(v1::Binding *binding, const clang::DynTypedNode &node,
                  const clang::ASTContext &context,
                  const fs::path &working_directory) {
  const auto &manager = context.getSourceManager();
  const auto &language = context.getLangOpts();
  binding->set_kind(node.getNodeKind().asStringRef().str());
  binding->set_semantic_kind(semantic_kind(node));

  llvm::StringRef source_text;
  const auto source_range = node.getSourceRange();
  if (source_range.isValid()) {
    const auto file_range = clang::Lexer::makeFileCharRange(
        clang::CharSourceRange::getTokenRange(source_range), manager, language);
    if (file_range.isValid() && manager.getFileID(file_range.getBegin()) ==
                                    manager.getFileID(file_range.getEnd())) {
      std::string file = manager.getFilename(file_range.getBegin()).str();
      if (!file.empty()) {
        fs::path absolute_file(file);
        if (absolute_file.is_relative()) {
          absolute_file = working_directory / absolute_file;
        }
        auto *range = binding->mutable_range();
        range->set_file(absolute_file.lexically_normal().string());
        set_position(range->mutable_start(), manager, file_range.getBegin());
        set_position(range->mutable_end(), manager, file_range.getEnd());
        bool invalid = false;
        source_text = clang::Lexer::getSourceText(file_range, manager, language,
                                                  &invalid);
        if (invalid) {
          source_text = {};
        }
      }
    }
  }
  binding->set_text(shortened(source_text, kMaximumTextBytes));
  binding->set_summary(summary(node, context, source_text));
  binding->set_node(node_identity(node, *binding));
}

class MatchCollector final : public am::MatchFinder::MatchCallback {
public:
  MatchCollector(v1::RunReply &reply, int query_index, uint32_t max_matches,
                 uint32_t &stored_matches, fs::path working_directory)
      : reply_(reply), query_index_(query_index), max_matches_(max_matches),
        stored_matches_(stored_matches),
        working_directory_(std::move(working_directory)) {}

  void run(const am::MatchFinder::MatchResult &result) override {
    auto *query = reply_.mutable_queries(query_index_);
    query->set_count(query->count() + 1);
    if (stored_matches_ >= max_matches_) {
      reply_.set_truncated(true);
      return;
    }
    ++stored_matches_;
    auto *match = query->add_matches();
    match->set_index(query->count());
    for (const auto &[id, node] : result.Nodes.getMap()) {
      auto *binding = match->add_bindings();
      binding->set_id(id);
      fill_binding(binding, node, *result.Context, working_directory_);
    }
  }

private:
  v1::RunReply &reply_;
  int query_index_;
  uint32_t max_matches_;
  uint32_t &stored_matches_;
  fs::path working_directory_;
};

class CompileDiagnostics final : public clang::DiagnosticConsumer {
public:
  explicit CompileDiagnostics(std::string &output) : output_(output) {}

  void HandleDiagnostic(clang::DiagnosticsEngine::Level level,
                        const clang::Diagnostic &diagnostic) override {
    clang::DiagnosticConsumer::HandleDiagnostic(level, diagnostic);
    if (level < clang::DiagnosticsEngine::Warning) {
      return;
    }
    llvm::SmallString<256> message;
    diagnostic.FormatDiagnostic(message);
    std::string line;
    if (diagnostic.hasSourceManager() && diagnostic.getLocation().isValid()) {
      const auto location = diagnostic.getSourceManager().getPresumedLoc(
          diagnostic.getLocation());
      if (location.isValid()) {
        line += std::string(location.getFilename()) + ":" +
                std::to_string(location.getLine()) + ":" +
                std::to_string(location.getColumn()) + ": ";
      }
    }
    line +=
        level == clang::DiagnosticsEngine::Warning ? "warning: " : "error: ";
    line += message.str().str() + "\n";
    if (truncated_) {
      return;
    }
    const size_t content_limit =
        kMaximumDiagnosticBytes - kDiagnosticTruncationMarker.size();
    if (line.size() <= content_limit - output_.size()) {
      output_ += line;
      return;
    }
    output_ += kDiagnosticTruncationMarker;
    truncated_ = true;
  }

private:
  std::string &output_;
  bool truncated_ = false;
};

} // namespace

v1::RunReply run_match_request(const v1::RunRequest &request) {
  v1::RunReply reply;
  if (request.source_path().empty()) {
    add_diagnostic(reply, 0, "sourcePath is required");
    return reply;
  }

  std::error_code error;
  const fs::path working_directory =
      request.working_directory().empty()
          ? fs::current_path(error)
          : fs::path(request.working_directory());
  if (error || !working_directory.is_absolute() ||
      !fs::is_directory(working_directory, error)) {
    add_diagnostic(reply, 0,
                   "workingDirectory must be an existing absolute directory");
    return reply;
  }
  fs::path source_path(request.source_path());
  if (source_path.is_relative()) {
    source_path = working_directory / source_path;
  }
  source_path = source_path.lexically_normal();
  if (!fs::is_regular_file(source_path, error)) {
    add_diagnostic(
        reply, 0, "sourcePath is not a readable file: " + source_path.string());
    return reply;
  }

  auto traversal = parse_traversal(request.traversal().empty()
                                       ? "AsIs"
                                       : llvm::StringRef(request.traversal()));
  if (!traversal) {
    add_diagnostic(reply, 0, "Unknown traversal: " + request.traversal());
    return reply;
  }

  const uint32_t max_matches =
      request.max_matches() == 0
          ? kDefaultMaxMatches
          : std::min(request.max_matches(), kMaximumMaxMatches);
  uint32_t stored_matches = 0;
  bool bind_root = true;
  dynamic::Parser::NamedValueMap named_values;
  dynamic::Parser::RegistrySema sema;
  std::vector<std::unique_ptr<MatchCollector>> collectors;
  am::MatchFinder finder;

  for (int index = 0; index < request.commands_size(); ++index) {
    const auto &command = request.commands(index);
    const int prior_diagnostics = reply.diagnostics_size();
    switch (command.kind()) {
    case v1::Command::LET: {
      if (!valid_identifier(command.name())) {
        add_diagnostic(reply, index, "LET requires a valid name");
        break;
      }
      llvm::StringRef code(command.expression());
      dynamic::VariantValue value;
      dynamic::Diagnostics diagnostics;
      if (!dynamic::Parser::parseExpression(code, &sema, &named_values, &value,
                                            &diagnostics) ||
          !trim(code).empty()) {
        const auto [line, column] = parser_position(diagnostics);
        add_diagnostic(reply, index, parser_message(diagnostics), line, column);
        break;
      }
      named_values[command.name()] = std::move(value);
      break;
    }
    case v1::Command::SET_TRAVERSAL: {
      const auto value =
          command.value().empty() ? command.expression() : command.value();
      auto parsed = parse_traversal(value);
      if (!parsed) {
        add_diagnostic(reply, index, "Unknown traversal: " + value);
      } else {
        traversal = parsed;
      }
      break;
    }
    case v1::Command::SET_BIND_ROOT: {
      const auto value =
          command.value().empty() ? command.expression() : command.value();
      auto parsed = parse_bool(value);
      if (!parsed) {
        add_diagnostic(reply, index, "set bind-root expects true or false");
      } else {
        bind_root = *parsed;
      }
      break;
    }
    case v1::Command::MATCH: {
      llvm::StringRef code(command.expression());
      dynamic::Diagnostics diagnostics;
      auto matcher = dynamic::Parser::parseMatcherExpression(
          code, &sema, &named_values, &diagnostics);
      if (!matcher || !trim(code).empty()) {
        const auto [line, column] = parser_position(diagnostics);
        add_diagnostic(reply, index, parser_message(diagnostics), line, column);
        break;
      }
      if (bind_root) {
        matcher->setAllowBind(true);
        if (auto bound = matcher->tryBind("root")) {
          matcher = std::move(bound);
        }
      }
      *matcher = matcher->withTraversalKind(*traversal);
      const int query_index = reply.queries_size();
      auto collector = std::make_unique<MatchCollector>(
          reply, query_index, max_matches, stored_matches, working_directory);
      if (!finder.addDynamicMatcher(*matcher, collector.get())) {
        add_diagnostic(reply, index,
                       "Matcher cannot be used at the root: " +
                           command.expression());
        break;
      }
      auto *query = reply.add_queries();
      query->set_command_index(index);
      query->set_matcher(command.expression());
      collectors.push_back(std::move(collector));
      break;
    }
    case v1::Command::KIND_UNSPECIFIED:
    default:
      add_diagnostic(reply, index, "Unknown command kind");
      break;
    }
    // clang-query's script mode stops at the first invalid command. Earlier
    // matchers are still executed below, in their original order.
    if (reply.diagnostics_size() != prior_diagnostics) {
      break;
    }
  }

  if (collectors.empty()) {
    return reply;
  }
  std::vector<std::string> flags(request.flags().begin(),
                                 request.flags().end());
  const bool has_resource_dir =
      std::any_of(flags.begin(), flags.end(), [](const std::string &flag) {
        return flag == "-resource-dir" || flag == "--resource-dir" ||
               flag.rfind("-resource-dir=", 0) == 0 ||
               flag.rfind("--resource-dir=", 0) == 0;
      });
  if (!has_resource_dir) {
    flags.insert(flags.begin(),
                 std::string("-resource-dir=") + ASTMATCHER_RESOURCE_DIR);
  }
  clang::tooling::FixedCompilationDatabase compilation_database(
      working_directory.string(), flags);
  clang::tooling::ClangTool tool(compilation_database, {source_path.string()});
  tool.appendArgumentsAdjuster(
      [](const clang::tooling::CommandLineArguments &arguments,
         llvm::StringRef) {
        auto adjusted = arguments;
        if (!adjusted.empty()) {
          adjusted[0] = ASTMATCHER_COMPILER_PATH;
        }
        return adjusted;
      });
  CompileDiagnostics diagnostic_consumer(*reply.mutable_stderr());
  tool.setDiagnosticConsumer(&diagnostic_consumer);
  tool.setPrintErrorMessage(false);
  auto factory = clang::tooling::newFrontendActionFactory(&finder);
  const int status = tool.run(factory.get());
  if (status != 0 && reply.stderr().empty()) {
    reply.set_stderr("Clang could not parse the source file\n");
  }
  if (status != 0) {
    add_diagnostic(reply, request.commands_size(),
                   "Clang failed to parse the source file");
  }
  return reply;
}

} // namespace astmatcher::native
