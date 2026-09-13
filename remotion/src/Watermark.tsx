import React from "react";
import { AbsoluteFill, useVideoConfig } from "remotion";
import { Monogram } from "./Monogram";

// Watermark permanent, reserve au Teaser (voir MemoraFilm.tsx) : c'est le
// format que les invites font circuler (Instagram, WhatsApp, statuts...), et
// beaucoup ne regardent pas jusqu'au carton de fin ou vit le sceau plein ecran.
// Ici la marque doit rester visible du debut a la fin, mais sans jamais rivaliser
// avec le contenu : petit, en coin, translucide, monochrome (pas d'accent dore
// qui attirerait l'oeil plus que le souvenir lui-meme).
export const Watermark: React.FC = () => {
  const { width, height } = useVideoConfig();
  const minSide = Math.min(width, height);
  const size = minSide * 0.08;
  const margin = minSide * 0.045;

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div
        style={{
          position: "absolute",
          right: margin,
          bottom: margin,
          filter: "drop-shadow(0 1px 6px rgba(0,0,0,0.5))",
        }}
      >
        <Monogram size={size} opacity={0.6} ringColor="#f4d9d5" markColor="#f4d9d5" />
      </div>
    </AbsoluteFill>
  );
};
