// Form-only guidance. The API's /changes/types response is authoritative for supported types.
// Keep domain validation in the backend; these hints only help the user enter its payload.
export const CHANGE_FORM_HINTS = Object.freeze({
  INTERPRETATION_VERSION: {
    label: "Interpretation table updated",
    nodeType: "interpretation_rule",
    lockNodeType: true,
    description: "Compare two stored interpretation versions automatically, or declare rule changes manually.",
  },
  MAPPING_ADDED: {
    label: "Mapping added or updated",
    nodeType: "mapping_rule",
    lockNodeType: true,
    description: "Name each affected mapping rule. Use an empty old entity version for a newly added rule.",
  },
  MAPPING_RETIRED: {
    label: "Mapping retired",
    nodeType: "mapping_rule",
    lockNodeType: true,
    description: "Name each retired mapping rule. Leave the entity's new version empty when removed.",
  },
  AST_CORRECTED: {
    label: "Phenotype evidence corrected",
    nodeType: "ast_evidence",
    lockNodeType: true,
    description: "Use registered AST evidence IDs and versions. Each row changes as a whole.",
  },
  GENOTYPE_CHANGED: {
    label: "Genotype evidence changed",
    nodeType: "genotype_evidence",
    lockNodeType: true,
    description: "Use registered genotype evidence IDs and versions. Each row changes as a whole.",
  },
  RULE_POLICY_REVISED: {
    label: "Rule policy revised",
    nodeType: "policy_rule",
    lockNodeType: false,
    description: "A policy rule ID is policy_id|value. The registered case-rule-version node is also permitted for a broad declaration.",
  },
  EVALUATOR_VERSION: {
    label: "Evaluator version changed",
    nodeType: "",
    lockNodeType: false,
    description: "Declare the registered versioned node IDs affected by this evaluator change; automatic derivation is not available.",
  },
});

export class ChangeFormError extends Error {
  constructor(field, message) {
    super(message);
    this.name = "ChangeFormError";
    this.field = field;
  }
}

export function changeTypeHint(type) {
  return CHANGE_FORM_HINTS[type] ?? {
    label: type,
    nodeType: "",
    lockNodeType: false,
    description: "Declare each changed entity using registered node IDs and versions.",
  };
}

export function suggestedEntity(type, oldVersion = "", newVersion = "") {
  return {
    node_type: changeTypeHint(type).nodeType,
    node_id: "",
    old_version: oldVersion,
    new_version: newVersion,
    changed_region: "",
  };
}

function text(value) {
  return String(value ?? "").trim();
}

function parseObjectField(value, field, label, nullable = false) {
  if (!text(value) && nullable) {
    return null;
  }
  let parsed;
  try {
    parsed = JSON.parse(text(value) || "{}");
  } catch {
    throw new ChangeFormError(field, label + " must be valid JSON.");
  }
  if (parsed === null || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new ChangeFormError(field, label + " must be a JSON object.");
  }
  return parsed;
}

export function buildChangePayload(fields, entities = []) {
  const changeId = text(fields.change_id);
  const type = text(fields.type);
  const oldVersion = text(fields.old_version);
  const newVersion = text(fields.new_version);
  const initiator = text(fields.initiator);
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$/.test(changeId)) {
    throw new ChangeFormError("change_id", "Use 1–100 letters, numbers, dots, underscores, colons or hyphens. No spaces.");
  }
  if (!type) {
    throw new ChangeFormError("type", "Choose a supported change type.");
  }
  if (!oldVersion) {
    throw new ChangeFormError("old_version", "Enter the old version.");
  }
  if (!newVersion) {
    throw new ChangeFormError("new_version", "Enter the new version.");
  }
  if (oldVersion === newVersion) {
    throw new ChangeFormError("new_version", "Old and new versions must differ.");
  }
  if (!initiator) {
    throw new ChangeFormError("initiator", "Enter the person or producer registering this change.");
  }
  const declaredScope = parseObjectField(fields.declared_scope, "declared_scope", "Declared scope");
  const derive = fields.derive_entities === true;
  if (derive && fields.can_derive_entities !== true) {
    throw new ChangeFormError("changed_entities", "Automatic entity derivation is not available for this type.");
  }
  if (!derive && entities.length === 0) {
    throw new ChangeFormError("changed_entities", "Add at least one changed entity.");
  }
  const changedEntities = derive ? [] : entities.map((item, index) => {
    const prefix = "changed_entities[" + index + "]";
    const nodeType = text(item.node_type);
    const nodeId = text(item.node_id);
    const old = text(item.old_version) || null;
    const next = text(item.new_version) || null;
    if (!nodeType) {
      throw new ChangeFormError(prefix + ".node_type", "Enter a registered node type.");
    }
    if (!nodeId) {
      throw new ChangeFormError(prefix + ".node_id", "Enter the registered node ID.");
    }
    if (!old && !next) {
      throw new ChangeFormError(prefix + ".old_version", "Set an old version, a new version, or both.");
    }
    if (old && next && old === next) {
      throw new ChangeFormError(prefix + ".new_version", "The entity's old and new versions must differ.");
    }
    const region = parseObjectField(item.changed_region, prefix + ".changed_region", "Changed region", true);
    return {
      node_type: nodeType,
      node_id: nodeId,
      old_version: old,
      new_version: next,
      changed_region: region,
    };
  });
  return {
    change_id: changeId,
    type,
    old_version: oldVersion,
    new_version: newVersion,
    changed_entities: changedEntities,
    declared_scope: declaredScope,
    initiator,
  };
}

// Both API domain errors and FastAPI schema errors are preserved, not replaced with generic text.
export function changeValidationIssues(error) {
  const details = error?.details;
  if (Array.isArray(details?.problems)) {
    return details.problems.map((message) => {
      const value = String(message);
      const entityMatch = value.match(/^(changed_entities\[\d+\]):\s*(.*)$/);
      if (entityMatch) {
        return { field: entityMatch[1], message: entityMatch[2] };
      }
      const basic = ["change_id", "initiator", "type", "old_version", "new_version", "declared_scope", "changed_entities"];
      const field = value.startsWith("unknown change type") ? "type"
        : value.startsWith("change type") && value.includes("changed_entities") ? "changed_entities"
        : basic.find((key) => value.startsWith(key + " ") || value.startsWith(key + ":")) ?? "form";
      return { field, message: value };
    });
  }
  if (Array.isArray(details)) {
    return details.map((item) => {
      const loc = Array.isArray(item?.loc) ? item.loc.filter((v) => v !== "body") : [];
      let field = "form";
      if (loc[0] === "changed_entities" && Number.isInteger(loc[1])) {
        field = "changed_entities[" + loc[1] + "]" + (loc[2] ? "." + loc[2] : "");
      } else if (typeof loc[0] === "string") {
        field = loc[0];
      }
      return { field, message: String(item?.msg ?? "Invalid field value") };
    });
  }
  if (error?.errorCode === "duplicate_change") {
    return [{ field: "change_id", message: String(error.message) }];
  }
  return [];
}
