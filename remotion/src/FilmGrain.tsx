import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";

// Grain de pellicule discret : une texture qui bouge legerement d'une frame a
// l'autre, comme un vrai grain argentique, plutot qu'un bruit fige qui lirait
// comme un filtre statique plaque sur l'image. `mix-blend-mode: overlay` laisse
// les tons moyens de l'image inchanges et ne fait que texturer ombres/hautes
// lumieres — l'effet reste sous le seuil de perception consciente.
//
// IMPORTANT (cout de rendu) : `feTurbulence` calcule sur tout le cadre (1920x1080)
// et refait ce calcul a CHAQUE frame est extremement couteux en rendu logiciel
// (SwiftShader, utilise par Chrome headless sur les containers Linux sans GPU —
// voir render.mjs) : jusqu'a plusieurs secondes par frame, ce qui suffit a lui
// seul a faire trainer un rendu de plusieurs centaines de frames pendant des
// dizaines de minutes. Ca passait inapercu en dev (GPU materiel local) mais
// plombait le rendu en production. Solution standard : calculer le bruit sur
// une petite tuile (128x128, ~120x moins de pixels) puis la repeter via un
// <pattern> SVG — le navigateur rasterise la tuile UNE fois et la recopie,
// au lieu de reevaluer le filtre sur toute la surface.
const TILE_SIZE = 128;

export const FilmGrain: React.FC = () => {
  const frame = useCurrentFrame();
  const seed = (frame % 6) + 1;
  const patternId = "memora-grain-pattern";
  const filterId = "memora-grain-filter";

  return (
    <AbsoluteFill style={{ pointerEvents: "none", mixBlendMode: "overlay", opacity: 0.05 }}>
      <svg width="100%" height="100%">
        <defs>
          <filter id={filterId} x="0%" y="0%" width="100%" height="100%">
            <feTurbulence
              type="fractalNoise"
              baseFrequency="0.9"
              numOctaves="1"
              seed={seed}
              stitchTiles="stitch"
              result="noise"
            />
            <feColorMatrix in="noise" type="matrix" values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 0.6 0" />
          </filter>
          <pattern id={patternId} width={TILE_SIZE} height={TILE_SIZE} patternUnits="userSpaceOnUse">
            <rect width={TILE_SIZE} height={TILE_SIZE} filter={`url(#${filterId})`} />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill={`url(#${patternId})`} />
      </svg>
    </AbsoluteFill>
  );
};
