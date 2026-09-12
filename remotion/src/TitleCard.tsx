import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { ACCENT_FONT, TITLE_FONT, ensureFonts } from "./fonts";

// Sceau discret du carton de fin : le monogramme grave de la marque, repris
// tel quel du logo (meme trace, meme anneau pointille) plutot qu'invente pour
// la video. Une signature de studio, pas juste un mot "Merci".
const Seal: React.FC<{ size: number; opacity: number }> = ({ size, opacity }) => (
  <svg width={size} height={size} viewBox="0 0 202 202" style={{ opacity, display: "block" }}>
    <ellipse
      cx="101"
      cy="101"
      rx="80"
      ry="82"
      fill="none"
      stroke="#d8b46a"
      strokeWidth="2.4"
      strokeDasharray="241.45 13"
      strokeDashoffset="-6.5"
    />
    <path d="M181,96.5 L185.2,101 L181,105.5 L176.8,101 Z" fill="#f4d9d5" />
    <path d="M21,96.5 L25.2,101 L21,105.5 L16.8,101 Z" fill="#f4d9d5" />
    <path
      d="M46,63 C44.5,87 43.2,113 43,139 L49,139 C51,113 54.5,91 57,72 L95,134 L101,142 L139,71 C141,93 144.8,117 146,139 L159,139 C159.2,113 157.8,87 156,63 L133,63 L105,122 L71,63 Z"
      fill="#f4d9d5"
    />
    <rect x="38.5" y="60" width="36" height="3" fill="#f4d9d5" />
    <rect x="129.5" y="60" width="34" height="3" fill="#f4d9d5" />
    <rect x="34" y="136.5" width="24" height="3" fill="#f4d9d5" />
    <rect x="140" y="136.5" width="25" height="3" fill="#f4d9d5" />
  </svg>
);

// Carton anime : le titre se revele en douceur, un filet dore se trace de part et
// d'autre du sous-titre. C'est ce qui fait qu'un film "commence" au lieu de
// demarrer sec. Typographie premium (Fraunces + Cormorant), accents FR corrects.
export const TitleCard: React.FC<{
  title: string;
  subtitle: string;
  durationInFrames: number;
  // Le sceau ne marque que la sortie : une signature de cloture, pas un logo
  // repete a chaque carton.
  showSeal?: boolean;
  // Ouverture a froid : le fond n'est plus le degrade encre, mais le plan qui
  // joue derriere (passe par le parent). Le texte se pose alors sur un voile
  // au lieu d'un carton plein, et n'apparait qu'apres `revealDelay` frames —
  // le temps de laisser l'emotion du plan respirer seule.
  transparentBg?: boolean;
  revealDelay?: number;
}> = ({ title, subtitle, durationInFrames, showSeal, transparentBg, revealDelay = 0 }) => {
  ensureFonts();
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const minSide = Math.min(width, height);
  // Le texte suit son propre chrono, decale de revealDelay ; le reste du plan
  // (fond, sortie) continue de suivre le temps reel de la sequence.
  const textFrame = Math.max(frame - revealDelay, 0);
  const sealOpacity = interpolate(textFrame, [6, 26], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const enter = spring({ frame: textFrame, fps, config: { damping: 200 }, durationInFrames: 34 });
  const titleY = interpolate(enter, [0, 1], [28, 0]);
  const titleOpacity = enter;

  // Leger zoom d'ensemble : la scene "respire" au lieu d'etre fige.
  const driftScale = interpolate(frame, [0, durationInFrames], [1.0, 1.03], {
    extrapolateRight: "clamp",
  });

  // Sortie en fondu sur les dernieres frames. En ouverture a froid, le fond est
  // le plan lui-meme : c'est la transition (fade) de la TransitionSeries qui
  // gere sa sortie, pas ce carton — double-fondu evite.
  const fadeOut = transparentBg
    ? 1
    : interpolate(
        frame,
        [durationInFrames - 14, durationInFrames],
        [1, 0],
        { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
      );

  // Voile qui monte progressivement sous le texte pour la lisibilite, sans
  // assombrir les 2-3 premieres secondes ou le plan doit rester net.
  const scrimOpacity = transparentBg
    ? interpolate(textFrame, [0, 20], [0, 0.55], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      })
    : 0;

  const ruleWidth = interpolate(enter, [0, 1], [0, minSide * 0.09]);
  const subtitleOpacity = interpolate(textFrame, [18, 38], [0, 1], {
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
        background: transparentBg
          ? "transparent"
          : "radial-gradient(130% 130% at 50% 42%, #221d1f 0%, #171314 70%, #100d0e 100%)",
        justifyContent: "center",
        alignItems: "center",
        opacity: fadeOut,
      }}
    >
      {transparentBg ? (
        <AbsoluteFill
          style={{
            background:
              "linear-gradient(0deg, rgba(10,8,9,0.75) 0%, rgba(10,8,9,0.35) 45%, rgba(10,8,9,0.08) 75%)",
            opacity: scrimOpacity,
          }}
        />
      ) : null}
      {showSeal ? (
        <Seal size={minSide * 0.1} opacity={sealOpacity * 0.92} />
      ) : null}
      <div
        style={{
          transform: `translateY(${titleY}px) scale(${driftScale})`,
          opacity: titleOpacity,
          marginTop: showSeal ? minSide * 0.03 : 0,
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
