import vm from "node:vm";
import { readFileSync } from "node:fs";
export async function loadCard(url, context, extra = "") {
  const cache = new Map();
  async function load(target, suffix = "") {
    const key = target.href;
    if (cache.has(key)) return cache.get(key);
    const module = new vm.SourceTextModule(readFileSync(target, "utf8") + suffix, {
      context,
      identifier: key,
      initializeImportMeta(meta) { meta.url = key; },
      importModuleDynamically: async (specifier, parent) => {
        const dependency = await load(new URL(specifier, parent.identifier));
        if (dependency.status === "linked") await dependency.evaluate();
        return dependency;
      },
    });
    cache.set(key, module);
    await module.link((specifier, parent) => load(new URL(specifier, parent.identifier)));
    return module;
  }
  const module = await load(url, extra);
  await module.evaluate();
  return module.namespace;
}
