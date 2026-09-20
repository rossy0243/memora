/**
 * Rend les cartons du livre d'or en IMAGES FIXES (PNG), en une seule passe.
 *
 *   node render-cards.mjs \
 *     --cards=/chemin/cards.json \
 *     --public-dir=/chemin/assets \
 *     [--progress-file=/chemin/progress.json]
 *
 * `cards.json` : [{ "output": "/chemin/card_0001.png", "frame": 60,
 *                   "props": { kind, title, subtitle, name, durationInFrames } }, ...]
 *
 * Le bundle webpack et Chrome ne sont demarres qu'UNE fois pour tous les cartons :
 * c'est ce qui rend l'operation rapide (quelques secondes pour 100 cartons)
 * face au rendu video d'origine. Sortie : "OK <n>" sur stdout, code != 0 sinon.
 */
import { bundle } from "@remotion/bundler";
import { openBrowser, renderStill, selectComposition } from "@remotion/renderer";
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
  const cardsPath = args.cards;
  const publicDir = args["public-dir"] || path.join(__dirname, "public");
  const progressFile = args["progress-file"];
  if (!cardsPath) {
    throw new Error("Usage: --cards=<json> [--public-dir=<dir>] [--progress-file=<json>]");
  }

  const cards = JSON.parse(readFileSync(cardsPath, "utf8"));
  if (!Array.isArray(cards) || cards.length === 0) {
    throw new Error("Aucun carton a rendre.");
  }

  const gl = process.env.REMOTION_GL || (process.platform === "linux" ? "swangle" : null);
  const chromiumOptions = gl ? { gl } : {};
  const parallel = Math.max(1, Number(process.env.REMOTION_CARD_CONCURRENCY || 3));
  const licenseKey = process.env.REMOTION_LICENSE_KEY;

  const fontsSrc = path.join(__dirname, "public", "fonts");
  const fontsDest = path.join(publicDir, "fonts");
  if (existsSync(fontsSrc) && path.resolve(fontsSrc) !== path.resolve(fontsDest)) {
    cpSync(fontsSrc, fontsDest, { recursive: true });
  }

  const t0 = Date.now();
  const serveUrl = await bundle({ entryPoint: path.join(__dirname, "src", "index.ts"), publicDir });
  const tBundle = Date.now();
  const browser = await openBrowser("chrome", { chromiumOptions });
  const tBrowser = Date.now();

  try {
    // Metadonnees (taille, fps) identiques pour tous les cartons : une seule
    // selection, puis on surcharge les props carton par carton.
    const baseComposition = await selectComposition({
      serveUrl,
      id: "GuestBookCard",
      inputProps: cards[0].props,
      puppeteerInstance: browser,
    });

    let done = 0;
    let next = 0;
    const writeProgress = () => {
      if (!progressFile) return;
      try {
        writeFileSync(progressFile, JSON.stringify({ progress: done / cards.length }));
      } catch {
        // best-effort : ne doit jamais faire echouer le rendu
      }
    };

    const worker = async () => {
      while (next < cards.length) {
        const card = cards[next++];
        await renderStill({
          composition: { ...baseComposition, props: card.props, defaultProps: card.props },
          serveUrl,
          output: card.output,
          frame: card.frame,
          inputProps: card.props,
          imageFormat: "png",
          puppeteerInstance: browser,
          ...(licenseKey ? { licenseKey } : {}),
          logLevel: "error",
        });
        done += 1;
        writeProgress();
      }
    };

    const tSelect = Date.now();
    await Promise.all(Array.from({ length: Math.min(parallel, cards.length) }, worker));
    // Chronologie (secondes) : repere quelle etape coute, sans instrumenter Python.
    process.stdout.write(
      `TIMINGS bundle=${((tBundle - t0) / 1000).toFixed(1)} chrome=${((tBrowser - tBundle) / 1000).toFixed(1)} ` +
        `select=${((tSelect - tBrowser) / 1000).toFixed(1)} stills=${((Date.now() - tSelect) / 1000).toFixed(1)} ` +
        `cards=${cards.length} parallel=${parallel}
`
    );
  } finally {
    await browser.close({ silent: true });
  }

  process.stdout.write(`OK ${cards.length}\n`);
}

main().catch((error) => {
  process.stderr.write(`RENDER_ERROR ${error?.stack || error}\n`);
  process.exit(1);
});
