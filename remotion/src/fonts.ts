import { continueRender, delayRender, staticFile } from "remotion";

// Polices premium auto-hebergees (OFL) — embarquees dans le bundle, aucune
// dependance reseau au rendu. Elles couvrent le latin etendu : les accents
// francais (é, è, ê, à, ç, î, ô, û…) s'affichent correctement, contrairement
// aux polices systeme absentes du Chrome headless de rendu (bug du tofu « □ »).
export const TITLE_FONT = "Playfair Display"; // serif haute-contraste, cartons
export const ACCENT_FONT = "Cormorant Garamond"; // serif delicat, sous-titres

let injected = false;

// Injecte les @font-face et bloque le rendu tant que les glyphes ne sont pas
// charges (delayRender), sinon Remotion capture des frames avant la police.
export function ensureFonts(): void {
  if (typeof document === "undefined" || injected) return;
  injected = true;

  const style = document.createElement("style");
  style.textContent = `
    @font-face {
      font-family: "${TITLE_FONT}";
      src: url("${staticFile("fonts/PlayfairDisplay-VF.ttf")}") format("truetype");
      font-weight: 400 900;
      font-style: normal;
      font-display: block;
    }
    @font-face {
      font-family: "${ACCENT_FONT}";
      src: url("${staticFile("fonts/CormorantGaramond-VF.ttf")}") format("truetype");
      font-weight: 300 700;
      font-style: normal;
      font-display: block;
    }
  `;
  document.head.appendChild(style);

  const handle = delayRender("loading-fonts");
  Promise.all([
    document.fonts.load(`700 64px "${TITLE_FONT}"`),
    document.fonts.load(`500 40px "${ACCENT_FONT}"`),
  ])
    .then(() => document.fonts.ready)
    .then(() => continueRender(handle))
    .catch(() => continueRender(handle));
}
