import { Suspense } from "react";

import { SalesLoading, SalesShell } from "@/components/sales/sales-shell";

export default function SalesPage() {
  return (
    <Suspense fallback={<SalesLoading />}>
      <SalesShell />
    </Suspense>
  );
}
