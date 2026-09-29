#include "matcher_engine.h"

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <filesystem>
#include <memory>
#include <optional>
#include <set>
#include <sstream>
#include <string>
#include <string_view>
#include <tuple>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

#include "compiler_config.h"
#include "clang/AST/ASTContext.h"
#include "clang/AST/ASTTypeTraits.h"
#include "clang/AST/Decl.h"
#include "clang/AST/DeclCXX.h"
#include "clang/AST/DeclTemplate.h"
#include "clang/AST/PrettyPrinter.h"
#include "clang/AST/Type.h"
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
constexpr size_t kMaximumGraphNodes = 256;
constexpr size_t kMaximumGraphEdges = 512;
constexpr unsigned kMaximumInheritanceDepth = 32;
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

std::string record_kind(const clang::RecordDecl &record) {
  return record.isClass() ? "class" : record.isStruct() ? "struct" : "union";
}

std::string diagnostic_name(const clang::NamedDecl &declaration,
                            const clang::ASTContext &context) {
  std::string name;
  llvm::raw_string_ostream stream(name);
  declaration.getNameForDiagnostic(stream, context.getPrintingPolicy(), true);
  stream.flush();
  return name;
}

std::string callable_signature(const clang::FunctionDecl &function,
                               const clang::ASTContext &context) {
  const std::string name = function.getQualifiedNameAsString();
  std::string signature;
  llvm::raw_string_ostream stream(signature);
  function.getType().print(stream, context.getPrintingPolicy(), name);
  stream.flush();
  // QualType's declarator printer wraps the placeholder in parentheses.
  // The name itself does not need grouping, even for a pointer return type.
  const std::string wrapped_name = "(" + name + ")";
  const size_t wrapped_start = signature.find(wrapped_name);
  if (wrapped_start != std::string::npos) {
    signature.replace(wrapped_start, wrapped_name.size(), name);
  }
  if (llvm::isa<clang::CXXConstructorDecl, clang::CXXDestructorDecl,
                clang::CXXConversionDecl>(function)) {
    const size_t name_start = signature.find(name);
    if (name_start != std::string::npos) return signature.substr(name_start);
  }
  return signature;
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
  if (const auto *named = node.get<clang::NamedDecl>()) {
    binding->set_qualified_name(named->getQualifiedNameAsString());
    if (const auto *value = llvm::dyn_cast<clang::ValueDecl>(named)) {
      binding->set_type(value->getType().getAsString());
    }
    if (const auto *function = llvm::dyn_cast<clang::FunctionDecl>(named)) {
      binding->set_signature(callable_signature(*function, context));
    }
    if (const auto *record = llvm::dyn_cast<clang::RecordDecl>(named)) {
      binding->set_record_kind(record_kind(*record));
      if (!record->getNameAsString().empty()) {
        const std::string identity = diagnostic_name(*record, context);
        binding->set_record_identity(identity);
        binding->set_qualified_name(identity);
      }
    }
  } else if (const auto *type = node.get<clang::QualType>()) {
    binding->set_type(type->getAsString());
  }
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

void add_inspect_diagnostic(v1::InspectRecordReply &reply,
                            const std::string &message) {
  reply.add_diagnostics()->set_message(message);
}

std::string access_name(clang::AccessSpecifier access) {
  switch (access) {
  case clang::AS_public: return "public";
  case clang::AS_protected: return "protected";
  case clang::AS_private: return "private";
  case clang::AS_none: return "";
  }
  return "";
}

const clang::RecordDecl *record_definition(const clang::RecordDecl *record) {
  if (!record) return nullptr;
  return record->getDefinition() ? record->getDefinition() : record;
}

const clang::RecordDecl *field_record_type(clang::QualType type) {
  type = type.getCanonicalType();
  while (!type.isNull()) {
    if (const auto *record = type->getAs<clang::RecordType>()) {
      return record_definition(record->getDecl());
    }
    if (type->isPointerType() || type->isReferenceType()) {
      type = type->getPointeeType();
    } else if (const auto *array = llvm::dyn_cast<clang::ArrayType>(type.getTypePtr())) {
      type = array->getElementType();
    } else {
      break;
    }
  }
  return nullptr;
}

class RecordGraph final {
public:
  RecordGraph(v1::InspectRecordReply &reply, const clang::ASTContext &context,
              fs::path working_directory)
      : reply_(reply), context_(context),
        working_directory_(std::move(working_directory)) {}

  void build(const clang::RecordDecl &record) {
    const std::string root = add_node(&record);
    if (root.empty()) return;
    reply_.set_record_id(root);
    std::vector<const clang::RecordDecl *> records;
    collect_topology(&record, records);
    add_template_relationships(records);
    add_members(records);
    add_field_types();
    reply_.set_ok(true);
  }

private:
  struct Member {
    const clang::NamedDecl *decl;
    llvm::StringRef kind;
  };

  std::string add_node(const clang::Decl *decl) {
    if (const auto *record = llvm::dyn_cast<clang::RecordDecl>(decl)) {
      decl = record_definition(record);
    }
    if (const auto found = ids_.find(decl); found != ids_.end()) {
      return found->second;
    }
    if (reply_.nodes_size() >= static_cast<int>(kMaximumGraphNodes)) {
      reply_.set_truncated(true);
      return {};
    }
    const std::string id = "n" + std::to_string(reply_.nodes_size() + 1);
    ids_[decl] = id;
    auto *node = reply_.add_nodes();
    node->set_id(id);
    const auto *named = llvm::cast<clang::NamedDecl>(decl);
    v1::Binding binding;
    fill_binding(&binding, clang::DynTypedNode::create(*decl), context_,
                 working_directory_);
    node->set_kind(binding.kind());
    node->set_name(named->getNameAsString().empty()
                       ? (binding.record_kind().empty() ? "<anonymous>"
                                                        : "<anonymous " + binding.record_kind() + ">")
                       : named->getNameAsString());
    node->set_qualified_name(binding.qualified_name());
    node->set_signature(binding.signature());
    node->set_type(binding.type());
    node->set_record_kind(binding.record_kind());
    node->set_record_identity(binding.record_identity());
    if (const auto *record = llvm::dyn_cast<clang::RecordDecl>(decl)) {
      node->set_definition_status(record->getDefinition() ? "defined" : "unresolved");
    }
    if (binding.has_range()) {
      *node->mutable_range() = binding.range();
    }
    return id;
  }

  void add_edge(const std::string &from, const std::string &to,
                llvm::StringRef kind, llvm::StringRef access = {},
                bool is_virtual = false) {
    if (from.empty() || to.empty()) return;
    const auto key = std::make_tuple(from, to, kind.str());
    if (!edges_.insert(key).second) return;
    if (reply_.edges_size() >= static_cast<int>(kMaximumGraphEdges)) {
      reply_.set_truncated(true);
      return;
    }
    auto *edge = reply_.add_edges();
    edge->set_from(from);
    edge->set_to(to);
    edge->set_kind(kind.str());
    edge->set_access(access.str());
    edge->set_is_virtual(is_virtual);
  }

  void collect_topology(const clang::RecordDecl *root,
                        std::vector<const clang::RecordDecl *> &records) {
    root = record_definition(root);
    std::vector<std::pair<const clang::RecordDecl *, unsigned>> pending{{root, 0}};
    expanded_.insert(root);
    for (size_t index = 0; index < pending.size(); ++index) {
      const auto [record, depth] = pending[index];
      if (depth > kMaximumInheritanceDepth) {
        reply_.set_truncated(true);
        continue;
      }
      records.push_back(record);
      const std::string owner = add_node(record);
      if (const auto *cxx = llvm::dyn_cast<clang::CXXRecordDecl>(record)) {
        for (const auto &base : cxx->bases()) {
          const auto *parent = record_definition(base.getType()->getAsCXXRecordDecl());
          if (!parent) continue;
          const std::string parent_id = add_node(parent);
          add_edge(owner, parent_id, "inherits", access_name(base.getAccessSpecifier()),
                   base.isVirtual());
          if (!parent_id.empty() && expanded_.insert(parent).second) {
            pending.emplace_back(parent, depth + 1);
          }
        }
      }
    }
  }

  void add_template_relationships(
      std::vector<const clang::RecordDecl *> &records) {
    std::unordered_set<const clang::RecordDecl *> included(records.begin(), records.end());
    const auto append_pattern = [&](const clang::RecordDecl *pattern) {
      pattern = record_definition(pattern);
      if (pattern && included.insert(pattern).second) records.push_back(pattern);
    };

    // Template patterns join the same bounded record list as inheritance
    // records, so their relationships are expanded and their members are
    // emitted with the rest of the diagram.
    for (size_t index = 0; index < records.size(); ++index) {
      const auto *record = records[index];
      if (const auto *partial =
              llvm::dyn_cast<clang::ClassTemplatePartialSpecializationDecl>(record)) {
        const std::string partial_id = add_node(partial);
        const auto *primary = partial->getSpecializedTemplate();
        if (primary) {
          const auto *primary_record = primary->getTemplatedDecl();
          const std::string primary_id = add_node(primary_record);
          add_edge(partial_id, primary_id, "specializes");
          if (!primary_id.empty()) append_pattern(primary_record);
        }
        continue;
      }

      const auto *specialization =
          llvm::dyn_cast<clang::ClassTemplateSpecializationDecl>(record);
      if (!specialization) continue;

      const auto kind = specialization->getSpecializationKind();
      const bool instantiation = clang::isTemplateInstantiation(kind);
      const auto *primary = specialization->getSpecializedTemplate();
      const std::string owner = add_node(specialization);

      // A partial specialization is the pattern actually instantiated, so
      // show that edge and let the pattern's specializes edge lead to primary.
      if (instantiation) {
        const auto pattern = specialization->getInstantiatedFrom();
        if (const auto *partial =
                pattern.dyn_cast<clang::ClassTemplatePartialSpecializationDecl *>()) {
          const std::string partial_id = add_node(partial);
          add_edge(owner, partial_id, "instantiates");
          if (!partial_id.empty()) append_pattern(partial);
          continue;
        }
      }

      if (primary) {
        const auto *primary_record = primary->getTemplatedDecl();
        const std::string primary_id = add_node(primary_record);
        add_edge(owner, primary_id, instantiation ? "instantiates" : "specializes");
        if (!primary_id.empty()) append_pattern(primary_record);
      }
    }
  }

  void add_members(const std::vector<const clang::RecordDecl *> &records) {
    std::vector<std::vector<Member>> members;
    members.reserve(records.size());
    for (const auto *record : records) {
      std::vector<const clang::FieldDecl *> fields;
      std::vector<const clang::CXXMethodDecl *> methods;
      for (const auto *field : record->fields()) {
        if (!field->isImplicit()) fields.push_back(field);
      }
      if (const auto *cxx = llvm::dyn_cast<clang::CXXRecordDecl>(record)) {
        for (const auto *method : cxx->methods()) {
          if (!method->isImplicit()) methods.push_back(method);
        }
      }
      auto &record_members = members.emplace_back();
      record_members.reserve(fields.size() + methods.size());
      for (size_t index = 0; index < std::max(fields.size(), methods.size()); ++index) {
        if (index < fields.size()) record_members.push_back({fields[index], "field"});
        if (index < methods.size()) record_members.push_back({methods[index], "method"});
      }
    }

    std::vector<size_t> next_member(records.size(), 0);
    bool remaining = true;
    while (remaining) {
      remaining = false;
      for (size_t index = 0; index < records.size(); ++index) {
        if (next_member[index] == members[index].size()) continue;
        remaining = true;
        if (reply_.nodes_size() >= static_cast<int>(kMaximumGraphNodes) ||
            reply_.edges_size() >= static_cast<int>(kMaximumGraphEdges)) {
          reply_.set_truncated(true);
          return;
        }
        const auto &member = members[index][next_member[index]++];
        const std::string member_id = add_node(member.decl);
        add_edge(ids_.at(records[index]), member_id, member.kind,
                 access_name(member.decl->getAccess()));
        if (const auto *field = llvm::dyn_cast<clang::FieldDecl>(member.decl)) {
          if (const auto *target = field_record_type(field->getType())) {
            field_types_.emplace_back(member_id, target);
          }
        }
      }
    }
  }

  void add_field_types() {
    for (const auto &[field_id, target] : field_types_) {
      if (reply_.edges_size() >= static_cast<int>(kMaximumGraphEdges)) {
        reply_.set_truncated(true);
        return;
      }
      add_edge(field_id, add_node(target), "fieldType");
    }
  }

  v1::InspectRecordReply &reply_;
  const clang::ASTContext &context_;
  fs::path working_directory_;
  std::unordered_map<const clang::Decl *, std::string> ids_;
  std::unordered_set<const clang::RecordDecl *> expanded_;
  std::set<std::tuple<std::string, std::string, std::string>> edges_;
  std::vector<std::pair<std::string, const clang::RecordDecl *>> field_types_;
};

class RecordCollector final : public am::MatchFinder::MatchCallback {
public:
  RecordCollector(fs::path file, v1::Position position, fs::path working_directory,
                  std::string record_identity)
      : file_(std::move(file)), position_(std::move(position)),
        working_directory_(std::move(working_directory)),
        record_identity_(std::move(record_identity)) {}

  void run(const am::MatchFinder::MatchResult &result) override {
    const auto *record = result.Nodes.getNodeAs<clang::RecordDecl>("record");
    if (!record || record->isImplicit()) return;
    v1::Binding binding;
    fill_binding(&binding, clang::DynTypedNode::create(*record),
                 *result.Context, working_directory_);
    if (!record_identity_.empty() && binding.record_identity() != record_identity_) return;
    if (!binding.has_range()) return;
    std::error_code file_error;
    const bool same_file = fs::equivalent(binding.range().file(), file_, file_error);
    if ((file_error && fs::path(binding.range().file()).lexically_normal() != file_) ||
        (!file_error && !same_file)) return;
    const auto &range = binding.range();
    const auto start = std::make_pair(range.start().line(), range.start().character());
    const auto end = std::make_pair(range.end().line(), range.end().character());
    const auto point = std::make_pair(position_.line(), position_.character());
    if (point < start || !(point < end)) return;
    const clang::RecordDecl *candidate = record_definition(record);
    if (record_identity_.empty()) {
      if (const auto *specialization =
              llvm::dyn_cast<clang::ClassTemplateSpecializationDecl>(record)) {
        if (specialization->getSpecializationKind() ==
            clang::TSK_ImplicitInstantiation) {
          const auto pattern = specialization->getSpecializedTemplateOrPartial();
          if (const auto *partial =
                  pattern.dyn_cast<clang::ClassTemplatePartialSpecializationDecl *>()) {
            candidate = record_definition(partial);
          } else if (const auto *primary = pattern.dyn_cast<clang::ClassTemplateDecl *>()) {
            candidate = record_definition(primary->getTemplatedDecl());
          }
        }
      }
    }
    const auto span = std::make_pair(end.first - start.first,
                                     end.first == start.first
                                         ? end.second - start.second : end.second);
    if (best_span_ && span > *best_span_) return;
    if (best_span_ && span == *best_span_) {
      if (candidate != selected_) ambiguous_ = true;
      return;
    }
    best_span_ = span;
    selected_ = candidate;
    ambiguous_ = false;
    graph_.Clear();
    RecordGraph(graph_, *result.Context, working_directory_).build(*selected_);
  }

  v1::InspectRecordReply finish() {
    if (!selected_) {
      add_inspect_diagnostic(graph_, record_identity_.empty()
          ? "No record definition contains this source position"
          : "Record definition with identity '" + record_identity_ +
                "' was not found at this source position");
    } else if (ambiguous_) {
      graph_.Clear();
      add_inspect_diagnostic(graph_, "Several record definitions share this source position");
    }
    return std::move(graph_);
  }

private:
  fs::path file_;
  v1::Position position_;
  fs::path working_directory_;
  std::string record_identity_;
  std::optional<std::pair<uint32_t, uint32_t>> best_span_;
  const clang::RecordDecl *selected_ = nullptr;
  bool ambiguous_ = false;
  v1::InspectRecordReply graph_;
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

v1::InspectRecordReply inspect_record_request(const v1::InspectRecordRequest &request) {
  v1::InspectRecordReply reply;
  if (request.source_path().empty() || request.file().empty() ||
      !request.has_position()) {
    add_inspect_diagnostic(reply, "sourcePath, file, and position are required");
    return reply;
  }
  std::error_code error;
  const fs::path working_directory =
      request.working_directory().empty()
          ? fs::current_path(error)
          : fs::path(request.working_directory());
  if (error || !working_directory.is_absolute() ||
      !fs::is_directory(working_directory, error)) {
    add_inspect_diagnostic(reply,
                           "workingDirectory must be an existing absolute directory");
    return reply;
  }
  auto absolute_path = [&](const std::string &path) {
    fs::path value(path);
    return (value.is_absolute() ? value : working_directory / value).lexically_normal();
  };
  const fs::path source_path = absolute_path(request.source_path());
  const fs::path file = absolute_path(request.file());
  if (!fs::is_regular_file(source_path, error)) {
    add_inspect_diagnostic(reply, "sourcePath is not a readable file: " +
                                      source_path.string());
    return reply;
  }
  if (!fs::is_regular_file(file, error)) {
    add_inspect_diagnostic(reply, "file is not a readable file: " + file.string());
    return reply;
  }

  RecordCollector collector(file, request.position(), working_directory,
                            request.record_identity());
  am::MatchFinder finder;
  finder.addMatcher(am::recordDecl(am::isDefinition()).bind("record"), &collector);
  std::vector<std::string> flags(request.flags().begin(), request.flags().end());
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
        if (!adjusted.empty()) adjusted[0] = ASTMATCHER_COMPILER_PATH;
        return adjusted;
      });
  std::string stderr;
  CompileDiagnostics diagnostic_consumer(stderr);
  tool.setDiagnosticConsumer(&diagnostic_consumer);
  tool.setPrintErrorMessage(false);
  auto factory = clang::tooling::newFrontendActionFactory(&finder);
  const int status = tool.run(factory.get());
  reply = collector.finish();
  reply.set_stderr(stderr);
  if (status != 0) {
    add_inspect_diagnostic(reply, "Clang failed to parse the translation unit");
    reply.set_ok(false);
  }
  return reply;
}

} // namespace astmatcher::native
