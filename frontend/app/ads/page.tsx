"use client";

import { FormEvent, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import {
  CompetitorAnalyzeResponse,
  CompetitorFetchResponse,
  CompetitorPageResolution,
  CompetitorResolveResponse,
  CompetitorWithAds,
  FacebookPageCandidate,
} from "@/lib/types";
import { useBrand } from "@/components/BrandProvider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";

export default function AdsPage() {
  const { selectedBrandId, selectedBrand } = useBrand();

  const [competitors, setCompetitors] = useState<CompetitorWithAds[]>([]);
  const [competitorInput, setCompetitorInput] = useState("");
  const [loadingAds, setLoadingAds] = useState(false);
  const [fetching, setFetching] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState("");
  const [statusMessage, setStatusMessage] = useState("");
  const [operationErrors, setOperationErrors] = useState<string[]>([]);
  const [pageResolutions, setPageResolutions] = useState<CompetitorPageResolution[]>([]);
  const [selectedPages, setSelectedPages] = useState<Record<string, FacebookPageCandidate>>({});

  async function loadAds() {
    if (!selectedBrandId) return;

    setLoadingAds(true);
    setError("");

    try {
      const data = await apiFetch<CompetitorWithAds[]>(
        `/competitors/ads/${selectedBrandId}`
      );
      setCompetitors(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load ads");
    } finally {
      setLoadingAds(false);
    }
  }

  useEffect(() => {
    void Promise.resolve().then(loadAds);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedBrandId]);

  async function fetchAdsForPages(
    resolutions: CompetitorPageResolution[],
    selections: Record<string, FacebookPageCandidate>
  ) {
    if (!selectedBrandId) return;
    setStatusMessage("");
    setOperationErrors([]);

    const competitorsToFetch = resolutions
      .map((resolution) => {
        const page = resolution.status === "resolved"
          ? resolution.page
          : selections[resolution.query];

        if (!page) return null;

        return {
          name: resolution.query,
          page_id: page.page_id,
          page_name: page.name,
        };
      })
      .filter(
        (
          competitor
        ): competitor is { name: string; page_id: string; page_name: string } =>
          competitor !== null
      );

    if (competitorsToFetch.length !== resolutions.length) {
      setError("Choose a page for each unresolved competitor.");
      return;
    }

    const result = await apiFetch<CompetitorFetchResponse>("/competitors/fetch", {
      method: "POST",
      body: JSON.stringify({
        brand_id: selectedBrandId,
        competitors: competitorsToFetch,
      }),
    });

    setStatusMessage(
      [
        `Fetched ${result.total_ads_fetched} new ads.`,
        `Added ${result.competitors_added} competitors.`,
        result.duplicate_ads_skipped > 0
          ? `Skipped ${result.duplicate_ads_skipped} duplicate ads.`
          : "",
      ]
        .filter(Boolean)
        .join(" ")
    );
    setOperationErrors(
      result.errors.map((item) => `${item.competitor}: ${item.error}`)
    );

    setCompetitorInput("");
    setPageResolutions([]);
    setSelectedPages({});
    await loadAds();
  }

  async function handleFetchAds(e: FormEvent) {
    e.preventDefault();

    if (!selectedBrandId) return;

    const names = competitorInput
      .split(",")
      .map((name) => name.trim())
      .filter(Boolean);

    if (names.length === 0) return;

    setFetching(true);
    setError("");
    setStatusMessage("");
    setOperationErrors([]);
    setPageResolutions([]);
    setSelectedPages({});

    try {
      const resolutionResponse = await apiFetch<CompetitorResolveResponse>(
        "/competitors/resolve-pages",
        {
          method: "POST",
          body: JSON.stringify({
            competitor_names: names,
          }),
        }
      );

      if (resolutionResponse.errors.length > 0) {
        setError(resolutionResponse.errors.map((item) => item.error).join(" "));
      }

      const unresolved = resolutionResponse.results.filter(
        (resolution) => resolution.status === "needs_confirmation"
      );

      if (unresolved.length > 0) {
        setPageResolutions(resolutionResponse.results);
        const defaults: Record<string, FacebookPageCandidate> = {};
        for (const resolution of unresolved) {
          if (resolution.candidates[0]) {
            defaults[resolution.query] = resolution.candidates[0];
          }
        }
        setSelectedPages(defaults);
        return;
      }

      await fetchAdsForPages(resolutionResponse.results, {});
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch ads");
    } finally {
      setFetching(false);
    }
  }

  async function handleConfirmFetch() {
    setFetching(true);
    setError("");
    setStatusMessage("");
    setOperationErrors([]);

    try {
      await fetchAdsForPages(pageResolutions, selectedPages);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch ads");
    } finally {
      setFetching(false);
    }
  }

  async function handleAnalyzeAll() {
    if (!selectedBrandId) return;

    setAnalyzing(true);
    setError("");
    setStatusMessage("Analysis started. This can take a few minutes because model calls are rate-limited.");
    setOperationErrors([]);

    try {
      const result = await apiFetch<CompetitorAnalyzeResponse>(`/competitors/analyze/${selectedBrandId}`, {
        method: "POST",
      });

      setStatusMessage(
        result.errors.length === 0
          ? `Analysis complete. Analyzed ${result.ads_analyzed} ads.`
          : `Analysis partially complete. Analyzed ${result.ads_analyzed} ads; ${result.errors.length} ads need attention.`
      );
      setOperationErrors(
        result.errors.map((item) => `Ad ${item.ad_id}: ${item.error}`)
      );

      await loadAds();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to analyze ads");
    } finally {
      setAnalyzing(false);
    }
  }

  if (!selectedBrandId) {
    return (
      <Card>
        <CardContent className="py-10">
          <p className="text-muted-foreground">
            Select or create a brand before fetching competitor ads.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-8">
      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">
            Competitor Ads
          </h1>
          <p className="text-muted-foreground">
            Selected brand: {selectedBrand?.name}
          </p>
        </div>

        <Button onClick={handleAnalyzeAll} disabled={analyzing}>
          {analyzing ? "Analyzing..." : "Analyze All"}
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Fetch competitor ads</CardTitle>
        </CardHeader>
        <CardContent>
          <form
            onSubmit={handleFetchAds}
            className="flex flex-col gap-3 md:flex-row"
          >
            <Input
              placeholder="Competitors separated by commas, e.g. Nike, Adidas"
              value={competitorInput}
              onChange={(e) => setCompetitorInput(e.target.value)}
            />
            <Button type="submit" disabled={fetching}>
              {fetching ? "Fetching..." : "Fetch Ads"}
            </Button>
          </form>

          {pageResolutions.length > 0 && (
            <div className="mt-5 space-y-4 rounded-lg border p-4">
              {pageResolutions.map((resolution) => {
                if (resolution.status === "resolved" && resolution.page) {
                  return (
                    <div key={resolution.query} className="flex items-center justify-between gap-3">
                      <div>
                        <p className="text-sm font-medium">{resolution.query}</p>
                        <p className="text-sm text-muted-foreground">
                          Matched {resolution.page.name}
                        </p>
                      </div>
                      <span className="text-sm text-muted-foreground">
                        Score {resolution.page.score}
                      </span>
                    </div>
                  );
                }

                return (
                  <div key={resolution.query} className="space-y-3">
                    <div>
                      <p className="text-sm font-medium">{resolution.query}</p>
                      <p className="text-sm text-muted-foreground">
                        Choose the Facebook page to fetch ads from.
                      </p>
                    </div>

                    <div className="grid gap-2 md:grid-cols-3">
                      {resolution.candidates.map((candidate) => {
                        const selected =
                          selectedPages[resolution.query]?.page_id === candidate.page_id;

                        return (
                          <button
                            key={candidate.page_id}
                            type="button"
                            onClick={() =>
                              setSelectedPages((current) => ({
                                ...current,
                                [resolution.query]: candidate,
                              }))
                            }
                            className={`rounded-lg border p-3 text-left text-sm transition ${
                              selected ? "border-primary bg-muted" : "hover:bg-muted"
                            }`}
                          >
                            <span className="block font-medium">{candidate.name}</span>
                            <span className="block text-muted-foreground">
                              {candidate.like_count.toLocaleString()} likes
                            </span>
                            <span className="block text-muted-foreground">
                              Score {candidate.score}
                            </span>
                          </button>
                        );
                      })}
                    </div>

                    {resolution.candidates.length === 0 && (
                      <p className="text-sm text-red-500">
                        No candidate pages found for this competitor.
                      </p>
                    )}
                  </div>
                );
              })}

              <Button
                type="button"
                onClick={handleConfirmFetch}
                disabled={fetching}
              >
                {fetching ? "Fetching..." : "Fetch Selected Pages"}
              </Button>
            </div>
          )}

          {error && <p className="mt-4 text-sm text-red-500">{error}</p>}
          {(statusMessage || operationErrors.length > 0) && (
            <StatusPanel
              message={statusMessage}
              errors={operationErrors}
            />
          )}
        </CardContent>
      </Card>

      {loadingAds && <p className="text-muted-foreground">Loading ads...</p>}

      {!loadingAds && competitors.length === 0 && (
        <Card>
          <CardContent className="py-10">
            <p className="text-muted-foreground">
              No competitors or ads found yet.
            </p>
          </CardContent>
        </Card>
      )}

      <div className="space-y-8">
        {competitors.map((competitor) => (
          <Card key={competitor.id}>
            <CardHeader>
              <CardTitle>
                {competitor.name} - {competitor.ads.length} ads
              </CardTitle>
            </CardHeader>

            <CardContent className="space-y-6">
              {competitor.ads.map((ad) => (
                <div key={ad.id}>
                  <div className="grid gap-6 lg:grid-cols-[360px_1fr]">
                    <div className="space-y-3">
                      {ad.image_urls?.map((url, index) => (
                        <div
                          key={`${url}-${index}`}
                          className="relative min-h-[260px] overflow-hidden rounded-xl border bg-muted"
                        >
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          <img
                            src={url}
                            alt={`Ad creative ${index + 1}`}
                            className="h-full max-h-[420px] w-full object-contain"
                          />
                        </div>
                      ))}
                    </div>

                    <div className="space-y-5">
                      <div>
                        <p className="mb-1 text-sm font-medium text-muted-foreground">
                          Copy
                        </p>
                        <p className="whitespace-pre-wrap rounded-lg bg-muted p-4 text-sm">
                          {ad.copy_text || "No copy available."}
                        </p>
                      </div>

                      <div className="grid gap-3 md:grid-cols-2">
                        <Field label="Format" value={ad.format} />
                        <Field label="Hook" value={ad.copy_hook} />
                        <Field label="CTA" value={ad.copy_cta} />
                        <Field label="Angle" value={ad.copy_angle} />
                        <Field label="Visual Style" value={ad.visual_style} />
                        <Field
                          label="Creative Category"
                          value={ad.creative_category}
                        />
                        <Field
                          label="People"
                          value={String(ad.has_people)}
                        />
                        <Field
                          label="Text Overlay"
                          value={String(ad.has_text_overlay)}
                        />
                        <Field label="UGC vs Produced" value={ad.ugc_vs_produced} />
                        <Field
                          label="Product Visibility"
                          value={ad.product_visibility}
                        />
                      </div>

                      <div>
                        <p className="mb-1 text-sm font-medium text-muted-foreground">
                          Strategy Summary
                        </p>
                        <p className="rounded-lg border p-4 text-sm">
                          {ad.analysis_summary || "Not analyzed yet."}
                        </p>
                      </div>

                      {ad.analysis_error && (
                        <div>
                          <p className="mb-1 text-sm font-medium text-red-600">
                            Analysis Error
                          </p>
                          <p className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
                            {ad.analysis_error}
                          </p>
                        </div>
                      )}
                    </div>
                  </div>

                  <Separator className="mt-6" />
                </div>
              ))}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

function Field({
  label,
  value,
}: {
  label: string;
  value?: string | null;
}) {
  return (
    <div className="rounded-lg border p-3">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className="mt-1 text-sm">{value || "-"}</p>
    </div>
  );
}

function StatusPanel({
  message,
  errors,
}: {
  message: string;
  errors: string[];
}) {
  return (
    <div className="mt-4 rounded-lg border bg-muted/40 p-4 text-sm">
      {message && <p>{message}</p>}

      {errors.length > 0 && (
        <div className="mt-3 space-y-2">
          <p className="font-medium text-red-600">Errors</p>
          <ul className="list-disc space-y-1 pl-5 text-red-600">
            {errors.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
