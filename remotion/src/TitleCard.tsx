import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { ACCENT_FONT, TITLE_FONT, ensureFonts } from "./fonts";

// Carton anime : le titre se revele en douceur, un filet dore se trace de part et
// d'autre du sous-titre. C'est ce qui fait qu'un film "commence" au lieu de
// demarrer sec. Typographie premium (Playfair + Cormorant), accents FR corrects.
export const TitleCard: React.FC<{
  title: string;
  subtitle: string;
  durationInFrames: number;
}> = ({ title, subtitle, durationInFrames }) => {
  ensureFonts();
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const minSide = Math.min(width, height);

  const enter = spring({ frame, fps, config: { damping: 200 }, durationInFrames: 34 });
  const titleY = interpolate(enter, [0, 1], [28, 0]);
  const titleOpacity = enter;

  // Leger zoom d'ensemble : la scene "respire" au lieu d'etre fige.
  const driftScale = interpolate(frame, [0, durationInFrames], [1.0, 1.03], {
    extrapolateRight: "clamp",
  });

  // Sortie en fondu sur les dernieres frames.
  const fadeOut = interpolate(
    frame,
    [durationInFrames - 14, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const ruleWidth = interpolate(enter, [0, 1], [0, minSide * 0.09]);
  const subtitleOpacity = interpolate(frame, [18, 38], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const gold = "#d8b46a";
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
        background: "radial-gradient(130% 130% at 50% 42%, #221d1f 0%, #171314 70%, #100d0e 100%)",
        justifyContent: "center",
        alignItems: "center",
        opacity: fadeOut,
      }}
    >
      <div
        style={{
          transform: `translateY(${titleY}px) scale(${driftScale})`,
          opacity: titleOpacity,
          color: "#fdfaf6",
          fontFamily: `"${TITLE_FONT}", Georgia, serif`,
          fontSize: minSide * 0.105,
          fontWeight: 700,
          textAlign: "center",
          padding: "0 8%",
          lineHeight: 1.04,
          letterSpacing: minSide * 0.0004,
          textShadow: "0 2px 18px rgba(0,0,0,0.35)",
        }}
      >
        {title}
      </div>

      {subtitle ? (
        <div
          style={{
            opacity: subtitleOpacity,
            display: "flex",
            alignItems: "center",
            gap: minSide * 0.028,
            margin: `${minSide * 0.038}px 0 0`,
          }}
        >
          {rule}
          <div
            style={{
              color: gold,
              fontFamily: `"${ACCENT_FONT}", Georgia, serif`,
              fontSize: minSide * 0.036,
              fontWeight: 500,
              letterSpacing: minSide * 0.011,
              textTransform: "uppercase",
              whiteSpace: "nowrap",
            }}
          >
            {subtitle}
          </div>
          {rule}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};
