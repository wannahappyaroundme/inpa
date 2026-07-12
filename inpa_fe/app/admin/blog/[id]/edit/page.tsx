"use client";

import { use } from "react";
import { useAdminGuard } from "@/lib/useAdminGuard";
import { BlogEditor } from "@/components/blog-editor";

export default function AdminBlogEditPage({ params }: { params: Promise<{ id: string }> }) {
  const ready = useAdminGuard();
  const { id } = use(params);
  if (!ready) return null;
  return <BlogEditor postId={Number(id)} />;
}
