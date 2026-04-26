"use client";

import { FormEvent, useState } from "react";
import { apiFetch } from "@/lib/api";
import { Brand } from "@/lib/types";
import { useBrand } from "@/components/BrandProvider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export default function HomePage() {
  const { selectedBrand, refreshBrands, setSelectedBrandId } = useBrand();

  const [name, setName] = useState("");
  const [websiteUrl, setWebsiteUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");

    try {
      const brand = await apiFetch<Brand>("/brand/setup", {
        method: "POST",
        body: JSON.stringify({
          name,
          website_url: websiteUrl,
        }),
      });

      await refreshBrands();
      setSelectedBrandId(brand.id);
      setName("");
      setWebsiteUrl("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create brand");
    } finally {
      setLoading(false);
    }
  }

  const valuePropsList: string[] = (() => {
    try {
      return selectedBrand?.value_props
        ? JSON.parse(selectedBrand.value_props)
        : [];
    } catch {
      return [];
    }
  })();

  return (
    <div className="grid gap-8 lg:grid-cols-[420px_1fr]">
      <Card>
        <CardHeader>
          <CardTitle>Set up brand</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <Input
              placeholder="Brand name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />

            <Input
              placeholder="Website URL"
              value={websiteUrl}
              onChange={(e) => setWebsiteUrl(e.target.value)}
              required
            />

            {error && <p className="text-sm text-red-500">{error}</p>}

            <Button type="submit" disabled={loading} className="w-full">
              {loading ? "Scraping and profiling..." : "Create Brand Profile"}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>
            {selectedBrand ? selectedBrand.name : "No brand selected"}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {!selectedBrand && (
            <p className="text-muted-foreground">
              Create or select a brand to view its profile.
            </p>
          )}

          {selectedBrand && (
            <div className="space-y-4">
              <div>
                <p className="text-sm text-muted-foreground">Website</p>
                <p>{selectedBrand.website_url}</p>
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <ProfileField label="Category" value={selectedBrand.category} />
                <ProfileField label="Positioning" value={selectedBrand.positioning} />
                <ProfileField label="Tone" value={selectedBrand.tone} />
                <ProfileField label="Audience" value={selectedBrand.target_audience} />
                <ProfileField label="Visual Style" value={selectedBrand.visual_style} />

                <div className="md:col-span-2">
                  <p className="mb-2 text-sm font-medium text-muted-foreground">
                    Value Props
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {valuePropsList.map((item, index) => (
                      <span
                        key={index}
                        className="rounded-full border px-3 py-1 text-sm"
                      >
                        {item}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function ProfileField({
  label,
  value,
}: {
  label: string;
  value?: string | null;
}) {
  return (
    <div>
      <p className="text-sm font-medium text-muted-foreground">{label}</p>
      <p>{value || "-"}</p>
    </div>
  );
}
