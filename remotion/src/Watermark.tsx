import React from "react";
import { AbsoluteFill, useVideoConfig } from "remotion";
import { Monogram } from "./Monogram";
import { TITLE_FONT } from "./fonts";

// Watermark permanent, reserve au Teaser (voir MemoraFilm.tsx) : c'est le
// format que les invites font circuler (Instagram, WhatsApp, statuts...), et
// beaucoup ne regardent pas jusqu'au carton de fin ou vit le sceau plein ecran.
// Ici la marque doit rester visible du debut a la fin, mais sans jamais rivaliser
// avec le contenu : en coin, monochrome (pas d'accent dore qui attirerait l'oeil plus que
// le souvenir lui-meme). En HAUT (le bas du cadre passait inapercu sur telephone) et
// accompagnee du mot « Memora » : ceux qui ne connaissent pas le monogramme
// comprennent d'ou vient la video.
export const Watermark: React.FC<{ topInset?: number }> = ({ topInset = 0 }) => {
  const { width, height } = useVideoConfig();
  const minSide = Math.min(width, height);
  const size = minSide * 0.125;
  const margin = minSide * 0.05;
  // topInset : hauteur des bandeaux cinema du film heros, sous lesquels le logo doit se poser.
  const topOffset = Math.max(height * 0.055, margin) + topInset;

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div
        style={{
          position: "absolute",
          right: margin,
          top: topOffset,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: minSide * 0.008,
          filter: "drop-shadow(0 1px 6px rgba(0,0,0,0.55))",
        }}
      >
        <Monogram size={size} opacity={0.95} ringColor="#f4d9d5" markColor="#f4d9d5" />
        <div
          style={{
            color: "#fdfaf6",
            opacity: 0.9,
            fontFamily: `"${TITLE_FONT}", Georgia, serif`,
            fontSize: minSide * 0.05,
            fontWeight: 700,
            letterSpacing: minSide * 0.002,
            lineHeight: 1,
          }}
        >
          Memora
        </div>
      </div>
    </AbsoluteFill>
  );
};
