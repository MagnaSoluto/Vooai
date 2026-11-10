/**
 * AdSense — só renderiza se VITE_ADSENSE_CLIENT + VITE_ADSENSE_SLOT.
 * Fora do board de sinal (Método / Conta).
 */
import { useEffect } from "react";

const CLIENT = import.meta.env.VITE_ADSENSE_CLIENT || "";
const SLOT = import.meta.env.VITE_ADSENSE_SLOT || "";

export default function AdSlot({ className = "" }) {
  useEffect(() => {
    if (!CLIENT || !SLOT) return undefined;
    const id = "vooai-adsense";
    if (!document.getElementById(id)) {
      const s = document.createElement("script");
      s.id = id;
      s.async = true;
      s.src = `https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=${CLIENT}`;
      s.crossOrigin = "anonymous";
      document.head.appendChild(s);
    }
    const t = window.setTimeout(() => {
      try {
        (window.adsbygoogle = window.adsbygoogle || []).push({});
      } catch {
        /* ignore */
      }
    }, 400);
    return () => window.clearTimeout(t);
  }, []);

  if (!CLIENT || !SLOT) return null;

  return (
    <div className={`ad-slot ${className}`.trim()} aria-hidden="true">
      <ins
        className="adsbygoogle"
        style={{ display: "block" }}
        data-ad-client={CLIENT}
        data-ad-slot={SLOT}
        data-ad-format="auto"
        data-full-width-responsive="true"
      />
    </div>
  );
}
