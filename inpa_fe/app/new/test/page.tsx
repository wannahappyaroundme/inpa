import { permanentRedirect } from "next/navigation";

export default function LegacyServiceLandingPage() {
  permanentRedirect("/");
}
