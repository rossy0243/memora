import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";

// Grain de pellicule discret : une texture qui bouge legerement d'une frame a
// l'autre, comme un vrai grain argentique, plutot qu'un bruit fige qui lirait
// comme un filtre statique plaque sur l'image. `feTurbulence` genere le bruit
// en SVG (pas d'assets a charger), `seed` varie toutes les 2 frames pour un
// scintillement subtil sans flicker agressif. `mix-blend-mode: overlay` laisse
// les tons moyens de l'image inchanges et ne fait que texturer ombres/hautes
// lumieres — l'effet reste sous le seuil de perception consciente.
export const FilmGrain: React.FC = () => {
  const frame = useCurrentFrame();
  const seed = (frame % 6) + 1;

  return (
    <AbsoluteFill style={{ pointerEvents: "none", mixBlendMode: "overlay", opacity: 0.05 }}>
      <svg width="100%" height="100%">
        <filter id="memora-grain">
          <feTurbulence
            type="fractalNoise"
            baseFrequency="0.9"
            numOctaves="2"
            seed={seed}
            stitchTiles="stitch"
            result="noise"
          />
          <feColorMatrix in="noise" type="matrix" values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 0.6 0" />
        </filter>
        <rect width="100%" height="100%" filter="url(#memora-grain)" />
      </svg>
    </AbsoluteFill>
  );
};
