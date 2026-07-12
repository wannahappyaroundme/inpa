"use client";

import { useAdminGuard } from "@/lib/useAdminGuard";
import { BlogEditor } from "@/components/blog-editor";

export default function AdminBlogNewPage() {
  const ready = useAdminGuard();
  if (!ready) return null;
  return <BlogEditor />;
}
