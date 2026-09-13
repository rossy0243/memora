import React from "react";

// Le monogramme "M" de la marque, trace identique au logo (static/img/memora-mark.svg) —
// jamais reinvente pour la video. Reutilise a deux endroits : en grand sur le
// carton de fin (Seal, cf. TitleCard.tsx) et en petit, permanent, sur le Teaser
// (Watermark.tsx) — c'est le format qui circule le plus aupres des invites,
// donc celui ou la marque doit rester visible du debut a la fin, pas seulement
// sur un carton que peu de monde regarde jusqu'au bout sur les reseaux.
export const Monogram: React.FC<{
  size: number;
  opacity?: number;
  // Deux tons par defaut (anneau dore, trace blush) comme sur le logo dans son
  // habillage sombre ; passer la meme couleur aux deux pour un rendu monochrome
  // (watermark discret sur fond variable, pas de gout de fete sur chaque plan).
  ringColor?: string;
  markColor?: string;
}> = ({ size, opacity = 1, ringColor = "#d8b46a", markColor = "#f4d9d5" }) => (
  <svg width={size} height={size} viewBox="0 0 202 202" style={{ opacity, display: "block" }}>
    <ellipse
      cx="101"
      cy="101"
      rx="80"
      ry="82"
      fill="none"
      stroke={ringColor}
      strokeWidth="2.4"
      strokeDasharray="241.45 13"
      strokeDashoffset="-6.5"
    />
    <path d="M181,96.5 L185.2,101 L181,105.5 L176.8,101 Z" fill={markColor} />
    <path d="M21,96.5 L25.2,101 L21,105.5 L16.8,101 Z" fill={markColor} />
    <path
      d="M46,63 C44.5,87 43.2,113 43,139 L49,139 C51,113 54.5,91 57,72 L95,134 L101,142 L139,71 C141,93 144.8,117 146,139 L159,139 C159.2,113 157.8,87 156,63 L133,63 L105,122 L71,63 Z"
      fill={markColor}
    />
    <rect x="38.5" y="60" width="36" height="3" fill={markColor} />
    <rect x="129.5" y="60" width="34" height="3" fill={markColor} />
    <rect x="34" y="136.5" width="24" height="3" fill={markColor} />
    <rect x="140" y="136.5" width="25" height="3" fill={markColor} />
  </svg>
);
