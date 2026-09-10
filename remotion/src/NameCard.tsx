import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { ACCENT_FONT, TITLE_FONT, ensureFonts } from "./fonts";

// Carton plein ecran insere avant chaque message du livre d'or :
// « De la part de » en filet dore, puis le nom en grand. Meme grammaire
// typographique que TitleCard, en plus sobre (pas de sous-titre, entree rapide).
export const NameCard: React.FC<{
  name: string;
  durationInFrames: number;
}> = ({ name, durationInFrames }) => {
  ensureFonts();
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const minSide = Math.min(width, height);

  const enter = spring({ frame, fps, config: { damping: 200 }, durationInFrames: 26 });
  const nameY = interpolate(enter, [0, 1], [22, 0]);
  const drift = interpolate(frame, [0, durationInFrames], [1.0, 1.025], {
    extrapolateRight: "clamp",
  });
  const fadeOut = interpolate(
    frame,
    [durationInFrames - 12, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );
  const kickerOpacity = interpolate(frame, [2, 16], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const ruleWidth = interpolate(enter, [0, 1], [0, minSide * 0.08]);

  const gold = "#d8b46a";
  const displayName = name.trim() || "Un invité";
  const rule = (
    <div
      style={{
        width: ruleWidth,
        height: Math.max(minSide * 0.0026, 1),
        background: `linear-gradient(90deg, rgba(216,180,106,0) 0%, ${gold} 50%, rgba(216,180,106,0) 100%)`,
      }}
    />
  );

  return (
    <AbsoluteFill
      style={{
        background:
          "radial-gradient(130% 130% at 50% 42%, #241d18 0%, #181310 70%, #100c0a 100%)",
        justifyContent: "center",
        alignItems: "center",
        opacity: fadeOut,
      }}
    >
      <div
        style={{
          opacity: kickerOpacity,
          display: "flex",
          alignItems: "center",
          gap: minSide * 0.026,
          marginBottom: minSide * 0.04,
        }}
      >
        {rule}
        <div
          style={{
            color: gold,
            fontFamily: `"${ACCENT_FONT}", Georgia, serif`,
            fontSize: minSide * 0.032,
            fontWeight: 500,
            letterSpacing: minSide * 0.012,
            textTransform: "uppercase",
            whiteSpace: "nowrap",
          }}
        >
          De la part de
        </div>
        {rule}
      </div>
      <div
        style={{
          transform: `translateY(${nameY}px) scale(${drift})`,
          opacity: enter,
          color: "#fdfaf6",
          fontFamily: `"${TITLE_FONT}", Georgia, serif`,
          fontSize: minSide * 0.092,
          fontWeight: 700,
          textAlign: "center",
          padding: "0 8%",
          lineHeight: 1.05,
          textShadow: "0 2px 18px rgba(0,0,0,0.4)",
        }}
      >
        {displayName}
      </div>
    </AbsoluteFill>
  );
};
