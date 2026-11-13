from copy import deepcopy


def merge(base, override):
    result = deepcopy(base)
    for key, value in override.items():
        if key in ("font", "paragraph"):
            result.setdefault(key, {}).update(deepcopy(value))
        elif key != "based_on":
            result[key] = deepcopy(value)
    return result


class StyleResolver:
    def __init__(self, styles):
        self.styles = styles
        self.builtins = {"body": {}, **styles["headings"], **styles["blocks"]}
        self.named = styles["named_styles"]

    def overrides(self, name):
        chain = []
        while name in self.named:
            entry = self.named[name]
            chain.append(entry)
            name = entry.get("based_on", "body")
        result = deepcopy(self.builtins[name])
        for entry in reversed(chain):
            result = merge(result, entry)
        return result

    def resolve(self, body="body", functional=None):
        base = {"font": self.styles["font"], "paragraph": self.styles["paragraph"]}
        result = merge(base, self.overrides(body))
        return merge(result, self.overrides(functional)) if functional else result
