"""Expose disjoint object branches as named tools for XML parameter parsers.

No arguments are synthesized: the model supplies every branch field, and both
branch validation and the original public tool schema remain authoritative.
"""
from copy import deepcopy


def split_discriminated_tools(tools):
    projected, bindings = [], {}
    names = {t.get('function', {}).get('name') for t in tools}
    for tool in tools:
        function = tool.get('function', {})
        schema = function.get('parameters', {})
        branches = schema.get('oneOf') if isinstance(schema, dict) else None
        variants = []
        if isinstance(branches, list) and set(schema) <= {'oneOf', 'description'}:
            for i, branch in enumerate(branches):
                props = branch.get('properties', {}) if isinstance(branch, dict) else {}
                discriminator = props.get('action', {}).get('enum')
                if (branch.get('type') != 'object' or branch.get('additionalProperties') is not False
                        or not isinstance(discriminator, list) or len(discriminator) != 1
                        or 'action' not in branch.get('required', [])):
                    variants = []
                    break
                name = f"{function['name']}__variant_{i}"
                if name in names or len(name) > 64:
                    variants = []
                    break
                variant = deepcopy(tool)
                variant['function'].update(name=name, parameters=deepcopy(branch),
                    description=str(function.get('description', '')) +
                    f" This variant uses action={discriminator[0]}; supply all required fields explicitly.")
                variants.append((variant, {'original_name': function['name'], 'schema': deepcopy(branch)}))
        if variants:
            for variant, binding in variants:
                projected.append(variant)
                bindings[variant['function']['name']] = binding
        else:
            projected.append(deepcopy(tool))
    return projected, bindings
