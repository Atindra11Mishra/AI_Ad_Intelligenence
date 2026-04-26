export type Brand = {
  id: number;
  name: string;
  website_url: string;
  category: string | null;
  positioning: string | null;
  tone: string | null;
  target_audience: string | null;
  value_props: string | null;   // JSON array as TEXT
  visual_style: string | null;
  created_at: string;
};

export type Ad = {
  id: number;
  competitor_id: number;
  ad_id_meta: string | null;
  format: string | null;
  image_urls: string[];
  copy_text: string | null;
  copy_hook: string | null;
  copy_cta: string | null;
  copy_angle: string | null;
  visual_style: string | null;
  has_people: boolean;
  has_text_overlay: boolean;
  ugc_vs_produced: string | null;
  product_visibility: string | null;
  creative_category: string | null;
  analysis_summary: string | null;
  analysis_error: string | null;
  fetched_at: string;
};

export type CompetitorWithAds = {
  id: number;
  brand_id: number;
  name: string;
  created_at: string;
  ads: Ad[];
};

export type FacebookPageCandidate = {
  page_id: string;
  name: string;
  page_profile_uri: string;
  like_count: number;
  is_verified: boolean;
  score: number;
};

export type CompetitorPageResolution = {
  status: "resolved" | "needs_confirmation";
  query: string;
  page?: FacebookPageCandidate;
  candidates: FacebookPageCandidate[];
};

export type CompetitorResolveResponse = {
  status: "success" | "partial_success";
  results: CompetitorPageResolution[];
  errors: { competitor: string; error: string }[];
};

export type CompetitorFetchResponse = {
  status: "success" | "partial_success";
  competitors_added: number;
  total_ads_fetched: number;
  duplicate_ads_skipped: number;
  errors: { competitor: string; error: string }[];
};

export type CompetitorAnalyzeResponse = {
  status: "success" | "partial_success";
  ads_analyzed: number;
  errors: { ad_id: string; error: string }[];
};

export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
};
