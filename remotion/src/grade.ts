import { FilmProps } from "./types";

// Accord colorimetrique applique a chaque plan, en CSS filter.
// Objectif : un rendu chaud, doux, pellicule — coherent d'un plan a l'autre,
// ce qui manquait au grade FFmpeg (teinte uniforme sans harmonisation).
export function gradeFilter(grade: FilmProps["grade"]): string {
  switch (grade) {
    case "romantic":
      // Peaux chaudes, contraste doux, legere desaturation cinema.
      return "saturate(1.06) contrast(1.06) brightness(1.02) sepia(0.08)";
    case "warm":
      return "saturate(1.12) contrast(1.05) brightness(1.03) sepia(0.05)";
    case "neutral":
    default:
      return "saturate(1.02) contrast(1.03)";
  }
}

// Vignette douce : concentre le regard, signature "film".
export const vignette =
  "radial-gradient(120% 120% at 50% 50%, rgba(0,0,0,0) 62%, rgba(0,0,0,0.28) 100%)";

// Split-tone : les ombres tirent vers le rose de la marque, les hautes lumieres
// vers le champagne — un accord colorimetrique complet (pas juste une teinte
// uniforme comme le CSS filter seul), pose en mix-blend-mode "soft-light" pour
// ne pas laver l'image. C'est ce qui manque a un simple `sepia()` : un vrai
// grade separe ombres/lumieres, comme un etalonnage cinema.
export function splitToneOverlay(grade: FilmProps["grade"]): string {
  switch (grade) {
    case "romantic":
      return "linear-gradient(160deg, rgba(159,79,95,0.16) 0%, rgba(159,79,95,0) 45%, rgba(216,180,106,0) 55%, rgba(216,180,106,0.14) 100%)";
    case "warm":
      return "linear-gradient(160deg, rgba(127,57,72,0.12) 0%, rgba(127,57,72,0) 45%, rgba(226,192,121,0) 55%, rgba(226,192,121,0.18) 100%)";
    case "neutral":
    default:
      return "linear-gradient(160deg, rgba(36,31,34,0.08) 0%, rgba(36,31,34,0) 50%, rgba(216,180,106,0) 55%, rgba(216,180,106,0.08) 100%)";
  }
}
