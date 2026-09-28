"use strict";

const RECORD_KINDS = new Set(["CXXRecordDecl", "RecordDecl"]);

function isRecordBinding(binding) {
  return !!binding && (RECORD_KINDS.has(binding.kind) ||
    ["class", "struct", "union"].includes(binding.recordKind));
}

function detailForBinding(binding) {
  if (!binding) return "";
  if (binding.signature) return binding.signature;
  const name = binding.qualifiedName || binding.name || "";
  if (isRecordBinding(binding) && name) return `${binding.recordKind || binding.semanticKind || "record"} ${name}`;
  if (name && binding.type) return `${name}: ${binding.type}`;
  if (name) return name;
  if (binding.type) return binding.type;
  return binding.summary || binding.kind || "";
}

module.exports = { isRecordBinding, detailForBinding };
