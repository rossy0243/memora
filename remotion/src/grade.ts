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
