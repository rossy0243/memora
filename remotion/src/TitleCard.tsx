import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

// Carton anime : le titre monte et se revele en douceur, un filet dore se trace.
// C'est ce qui fait qu'un film "commence" au lieu de demarrer sec.
export const TitleCard: React.FC<{
  title: string;
  subtitle: string;
  durationInFrames: number;
}> = ({ title, subtitle, durationInFrames }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const minSide = Math.min(width, height);

  const enter = spring({ frame, fps, config: { damping: 200 }, durationInFrames: 30 });
  const titleY = interpolate(enter, [0, 1], [24, 0]);
  const titleOpacity = enter;

  // Sortie en fondu sur les dernieres frames.
  const fadeOut = interpolate(
    frame,
    [durationInFrames - 12, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const ruleWidth = interpolate(enter, [0, 1], [0, minSide * 0.12]);
  const subtitleOpacity = interpolate(frame, [16, 34], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill
      style={{
        backgroundColor: "#1c181a",
        justifyContent: "center",
        alignItems: "center",
        opacity: fadeOut,
        fontFamily: "Georgia, 'Times New Roman', serif",
      }}
    >
      <div
        style={{
          transform: `translateY(${titleY}px)`,
          opacity: titleOpacity,
          color: "#fdfaf6",
          fontSize: minSide * 0.09,
          fontWeight: 700,
          textAlign: "center",
          padding: "0 8%",
          lineHeight: 1.05,
        }}
      >
        {title}
      </div>
      <div
        style={{
          width: ruleWidth,
          height: Math.max(minSide * 0.004, 2),
          background: "#d8b46a",
          margin: `${minSide * 0.03}px 0`,
        }}
      />
      {subtitle ? (
        <div
          style={{
            opacity: subtitleOpacity,
            color: "#d8b46a",
            fontSize: minSide * 0.032,
            letterSpacing: minSide * 0.008,
            textTransform: "uppercase",
          }}
        >
          {subtitle}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};
