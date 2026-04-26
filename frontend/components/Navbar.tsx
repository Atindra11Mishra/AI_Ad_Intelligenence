"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useBrand } from "@/components/BrandProvider";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

function navClass(active: boolean) {
  return active
    ? "text-foreground font-semibold"
    : "text-muted-foreground hover:text-foreground";
}

export default function Navbar() {
  const pathname = usePathname();
  const { brands, selectedBrandId, setSelectedBrandId } = useBrand();

  return (
    <header className="border-b bg-background">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
        <div className="flex items-center gap-8">
          <Link href="/" className="text-xl font-bold tracking-tight">
            Brandora
          </Link>

          <nav className="flex items-center gap-5 text-sm">
            <Link href="/" className={navClass(pathname === "/")}>
              Home
            </Link>
            <Link href="/ads" className={navClass(pathname === "/ads")}>
              Ads
            </Link>
            <Link href="/chat" className={navClass(pathname === "/chat")}>
              Chat
            </Link>
          </nav>
        </div>

        <div className="w-64">
          <Select
            value={selectedBrandId ? String(selectedBrandId) : ""}
            onValueChange={(value) => setSelectedBrandId(Number(value))}
          >
            <SelectTrigger>
              <SelectValue placeholder="Select brand" />
            </SelectTrigger>
            <SelectContent>
              {brands.map((brand) => (
                <SelectItem key={brand.id} value={String(brand.id)}>
                  {brand.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
    </header>
  );
}