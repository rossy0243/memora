import { registerRoot } from "remotion";
import { RemotionRoot } from "./Root";
import { ensureFonts } from "./fonts";

// Charge les polices premium avant tout rendu (bloque via delayRender).
ensureFonts();

registerRoot(RemotionRoot);
