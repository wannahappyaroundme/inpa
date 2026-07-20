import { permanentRedirect } from "next/navigation";

export default function LegacyStoryPage() {
  permanentRedirect("/story");
}
