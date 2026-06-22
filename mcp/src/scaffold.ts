/** Turn a chosen component into files the trader writes into THEIR app, plus the
 *  exact `include` its data needs and how to wire it to the API. */
import { COMPONENTS, getComponent } from "./components.js";

export interface ScaffoldFile {
  path: string;
  content: string;
}

export interface ScaffoldResult {
  componentId: string;
  componentName: string;
  files: ScaffoldFile[];
  include: string[];
  peerDeps: string[];
  instructions: string;
}

export interface ScaffoldOptions {
  targetDir?: string;
  componentName?: string;
}

export function scaffoldComponent(id: string, opts: ScaffoldOptions = {}): ScaffoldResult {
  const spec = getComponent(id);
  if (!spec) {
    const available = COMPONENTS.map((c) => c.id).join(", ");
    throw new Error(
      `No existe el componente '${id}'. Disponibles: ${available}. Usa list_components.`,
    );
  }
  const componentName = (opts.componentName ?? spec.defaultName).replace(/[^A-Za-z0-9_]/g, "") || spec.defaultName;
  const dir = (opts.targetDir ?? "src/components/edgecute").replace(/\/+$/, "");
  const path = `${dir}/${componentName}.tsx`;
  const content = spec.render({ componentName });

  const includeStr = JSON.stringify(spec.include);
  const peer = spec.peerDeps.length ? `\n  • Instala dependencias: npm i ${spec.peerDeps.join(" ")}` : "";
  const instructions =
    `Componente '${spec.title}' escrito en ${path}.\n` +
    `  • Datos que necesita: pide el backtest con include=${includeStr} y pásale la sección correspondiente.${peer}\n` +
    `  • Tu app llama a la API en runtime (genera el cliente con generate_api_client).`;

  return {
    componentId: id,
    componentName,
    files: [{ path, content }],
    include: spec.include,
    peerDeps: spec.peerDeps,
    instructions,
  };
}
