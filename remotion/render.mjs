/**
 * Pont Django -> Remotion : rend une composition en MP4 a partir d'un JSON de props.
 *
 * Appele par le worker Python en sous-processus (comme il appelle deja ffmpeg) :
 *
 *   node render.mjs \
 *     --composition=Teaser \
 *     --props=/chemin/props.json \
 *     --output=/chemin/sortie.mp4 \
 *     --public-dir=/chemin/assets
 *
 * Les chemins de medias dans les props sont resolus par staticFile() relativement
 * a --public-dir : Django y depose les clips et la musique materialises depuis R2.
 *
 * Sortie : "OK <chemin>" sur stdout en cas de succes, code de sortie != 0 sinon.
 */
import { bundle } from "@remotion/bundler";
import { renderMedia, selectComposition } from "@remotion/renderer";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function parseArgs(argv) {
  const args = {};
  for (const raw of argv.slice(2)) {
    const match = raw.match(/^--([^=]+)=(.*)$/);
    if (match) args[match[1]] = match[2];
  }
  return args;
}

async function main() {
  const args = parseArgs(process.argv);
  const composition = args.composition;
  const propsPath = args.props;
  const output = args.output;
  const publicDir = args["public-dir"] || path.join(__dirname, "public");

  if (!composition || !propsPath || !output) {
    throw new Error("Usage: --composition=<id> --props=<json> --output=<mp4> [--public-dir=<dir>]");
  }

  const inputProps = JSON.parse(readFileSync(propsPath, "utf8"));
  const entryPoint = path.join(__dirname, "src", "index.ts");

  const serveUrl = await bundle({ entryPoint, publicDir });

  const comp = await selectComposition({
    serveUrl,
    id: composition,
    inputProps,
  });

  await renderMedia({
    composition: comp,
    serveUrl,
    codec: "h264",
    crf: 18,
    outputLocation: output,
    inputProps,
    // Deterministe, verbeux minimal : le worker Python journalise deja.
    logLevel: "error",
  });

  process.stdout.write(`OK ${output}\n`);
}

main().catch((error) => {
  process.stderr.write(`RENDER_ERROR ${error?.stack || error}\n`);
  process.exit(1);
});
