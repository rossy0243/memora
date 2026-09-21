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
import { cpSync, existsSync, readFileSync, writeFileSync } from "node:fs";
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
  // Optionnel : Django y lit la progression pendant que ce process tourne, pour
  // afficher un pourcentage qui avance vraiment plutot que fige le temps du rendu
  // (voir processing.remotion.render_movie_with_remotion).
  const progressFile = args["progress-file"];

  if (!composition || !propsPath || !output) {
    throw new Error("Usage: --composition=<id> --props=<json> --output=<mp4> [--public-dir=<dir>]");
  }

  const inputProps = JSON.parse(readFileSync(propsPath, "utf8"));
  const entryPoint = path.join(__dirname, "src", "index.ts");

  // En prod (Docker Linux sans GPU) : rendu OpenGL logiciel SwiftShader, sinon
  // Chrome refuse de peindre. En local on laisse Remotion choisir.
  const gl = process.env.REMOTION_GL || (process.platform === "linux" ? "swangle" : null);
  const chromiumOptions = gl ? { gl } : {};
  // Le worker Render a peu de CPU : REMOTION_CONCURRENCY=1 evite de saturer.
  const concurrency = process.env.REMOTION_CONCURRENCY
    ? Number(process.env.REMOTION_CONCURRENCY)
    : null;

  // Echelle du rendu (1 = 1920x1080 pour le film, 1080x1920 pour le teaser). 0.6667 = 1280x720 : environ
  // 2,25 fois moins de pixels a peindre par le rendu logiciel (pas de GPU sur Render), donc bien plus vite.
  // REMOTION_SCALE ne change que la taille du fichier final, pas le montage.
  const scale = process.env.REMOTION_SCALE ? Number(process.env.REMOTION_SCALE) : 1;

  // Licence Remotion : le jour ou Memora depasse 3 personnes, poser la cle du
  // dashboard remotion.pro (page « License keys ») dans REMOTION_LICENSE_KEY.
  // Absente = licence gratuite, comportement inchange. La telemetrie de licence
  // ne bloque et ne fait JAMAIS echouer un rendu (doc officielle).
  const licenseKey = process.env.REMOTION_LICENSE_KEY;

  // Cache des frames OffthreadVideo : sans plafond, Remotion peut viser une
  // grosse part de la RAM libre — fatal sur le worker 2 Go ou Node, Chrome et
  // ffmpeg cohabitent. 256 Mo par defaut sous Linux, ajustable via
  // REMOTION_OFFTHREAD_CACHE_MB.
  const offthreadCacheMb = process.env.REMOTION_OFFTHREAD_CACHE_MB
    ? Number(process.env.REMOTION_OFFTHREAD_CACHE_MB)
    : process.platform === "linux"
      ? 256
      : null;

  // Les polices premium (accents FR compris) vivent dans remotion/public/fonts.
  // staticFile() les resout depuis --public-dir ; on les y copie donc pour que la
  // chaine Django (public-dir = dossier d'assets materialises) les trouve aussi.
  const fontsSrc = path.join(__dirname, "public", "fonts");
  const fontsDest = path.join(publicDir, "fonts");
  if (existsSync(fontsSrc) && path.resolve(fontsSrc) !== path.resolve(fontsDest)) {
    cpSync(fontsSrc, fontsDest, { recursive: true });
  }

  const serveUrl = await bundle({ entryPoint, publicDir });

  const comp = await selectComposition({
    serveUrl,
    id: composition,
    inputProps,
    chromiumOptions,
  });

  // Ecrit la progression (0-1) dans un fichier que Django relit periodiquement,
  // au lieu d'un pourcentage fige pendant tout le rendu. Throttle a 1% pres pour
  // ne pas ecrire un fichier a chaque frame (renderMedia appelle onProgress tres
  // souvent). Ecriture best-effort : une erreur ici ne doit jamais faire echouer
  // le rendu lui-meme.
  let lastWrittenPercent = -1;
  const onProgress = progressFile
    ? ({ progress }) => {
        const percent = Math.round(progress * 100);
        if (percent === lastWrittenPercent) return;
        lastWrittenPercent = percent;
        try {
          writeFileSync(progressFile, JSON.stringify({ progress }));
        } catch {
          // best-effort, voir commentaire ci-dessus
        }
      }
    : undefined;

  await renderMedia({
    composition: comp,
    serveUrl,
    codec: "h264",
    crf: 18,
    outputLocation: output,
    inputProps,
    chromiumOptions,
    concurrency,
    ...(scale && scale !== 1 ? { scale } : {}),
    ...(offthreadCacheMb ? { offthreadVideoCacheSizeInBytes: offthreadCacheMb * 1024 * 1024 } : {}),
    // L'option n'est passee que si la cle existe : aucun impact tant que la
    // licence gratuite s'applique.
    ...(licenseKey ? { licenseKey } : {}),
    ...(onProgress ? { onProgress } : {}),
    // Deterministe, verbeux minimal : le worker Python journalise deja.
    logLevel: "error",
  });

  process.stdout.write(`OK ${output}\n`);
}

main().catch((error) => {
  process.stderr.write(`RENDER_ERROR ${error?.stack || error}\n`);
  process.exit(1);
});
