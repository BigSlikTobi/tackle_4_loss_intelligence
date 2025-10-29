// @ts-nocheck

import { createClient } from "https://esm.sh/v135/@supabase/supabase-js@2.43.1?target=deno";

const supabaseUrl = Deno.env.get("SUPABASE_URL");
const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");

if (!supabaseUrl || !serviceRoleKey) {
  throw new Error(
    "Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY environment variables.",
  );
}

const supabase = createClient(supabaseUrl, serviceRoleKey, {
  auth: { persistSession: false },
});

class HttpError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

type JsonBody = Record<string, unknown> | unknown[];

type TeamArticleRow = {
  id: string;
  headline: string | null;
  sub_headline: string | null;
  introduction: string | null;
  content: string | null;
  created_at: string;
};

type TeamArticleImageRow = {
  team_article_id_en: string | null;
  team_article_id_de: string | null;
  image_id_1: string | null;
  image_id_2: string | null;
};

type ArticleImageRow = {
  id: string;
  image_url: string | null;
  source: string | null;
};

interface TeamArticleResponse {
  headline: string | null;
  sub_headline: string | null;
  introduction: string | null;
  content: string | null;
  image_1: {
    image_url: string | null;
    source: string | null;
  } | null;
  image_2: {
    image_url: string | null;
    source: string | null;
  } | null;
  created_at: string;
}

function jsonResponse(body: JsonBody, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": "*",
    },
  });
}

function handleOptions(): Response {
  return new Response(null, {
    status: 204,
    headers: {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET,OPTIONS",
      "Access-Control-Allow-Headers": "content-type",
    },
  });
}

async function fetchTeamArticles(
  teamAbbr: string,
  languageCode: string,
): Promise<TeamArticleResponse[]> {
  // Fetch team articles filtered by team and language_code
  const { data: articles, error: articlesError } = await supabase
    .from<TeamArticleRow>("team_article")
    .select("id,headline,sub_headline,introduction,content,created_at")
    .eq("team", teamAbbr)
    .eq("language", languageCode)
    .order("created_at", { ascending: false });

  if (articlesError) {
    console.error("Failed to fetch team articles", articlesError);
    throw new HttpError(
      500,
      `Failed to load team articles: ${articlesError.message}`,
    );
  }

  if (!articles || articles.length === 0) {
    return [];
  }

  // Extract article IDs for image lookup
  const articleIds = articles.map((article) => article.id);

  // Determine the correct team_article_id column based on language code
  const languageIdColumn = languageCode === "en"
    ? "team_article_id_en"
    : languageCode === "de"
    ? "team_article_id_de"
    : null;

  if (!languageIdColumn) {
    throw new HttpError(
      400,
      `Unsupported language code: ${languageCode}. Supported: 'en', 'de'.`,
    );
  }

  // Fetch team article images
  const { data: articleImages, error: imagesError } = await supabase
    .from<TeamArticleImageRow>("team_article_image")
    .select("team_article_id_en,team_article_id_de,image_id_1,image_id_2")
    .in(languageIdColumn, articleIds);

  if (imagesError) {
    console.error("Failed to fetch team article images", imagesError);
    throw new HttpError(
      500,
      `Failed to load team article images: ${imagesError.message}`,
    );
  }

  // Build a map of article ID to image IDs
  const articleImageMap = new Map<
    string,
    { image_id_1: string | null; image_id_2: string | null }
  >();

  for (const imageRow of articleImages ?? []) {
    const articleId = languageCode === "en"
      ? imageRow.team_article_id_en
      : imageRow.team_article_id_de;

    if (articleId) {
      articleImageMap.set(articleId, {
        image_id_1: imageRow.image_id_1,
        image_id_2: imageRow.image_id_2,
      });
    }
  }

  // Collect all unique image IDs to fetch from article_images table
  const imageIds = new Set<string>();
  for (const imageData of articleImageMap.values()) {
    if (imageData.image_id_1) imageIds.add(imageData.image_id_1);
    if (imageData.image_id_2) imageIds.add(imageData.image_id_2);
  }

  // Fetch image URLs and sources
  let imageDetailsMap = new Map<
    string,
    { image_url: string | null; source: string | null }
  >();

  if (imageIds.size > 0) {
    const { data: imageDetails, error: imageDetailsError } = await supabase
      .from<ArticleImageRow>("article_images")
      .select("id,image_url,source")
      .in("id", Array.from(imageIds));

    if (imageDetailsError) {
      console.error("Failed to fetch article images", imageDetailsError);
      throw new HttpError(
        500,
        `Failed to load article images: ${imageDetailsError.message}`,
      );
    }

    for (const img of imageDetails ?? []) {
      imageDetailsMap.set(img.id, {
        image_url: img.image_url,
        source: img.source,
      });
    }
  }

  // Combine articles with their images
  const results: TeamArticleResponse[] = articles.map((article) => {
    const imageData = articleImageMap.get(article.id);

    let image_1 = null;
    let image_2 = null;

    if (imageData) {
      if (imageData.image_id_1) {
        const img1 = imageDetailsMap.get(imageData.image_id_1);
        if (img1) {
          image_1 = img1;
        }
      }

      if (imageData.image_id_2) {
        const img2 = imageDetailsMap.get(imageData.image_id_2);
        if (img2) {
          image_2 = img2;
        }
      }
    }

    return {
      headline: article.headline,
      sub_headline: article.sub_headline,
      introduction: article.introduction,
      content: article.content,
      image_1,
      image_2,
      created_at: article.created_at,
    };
  });

  return results;
}

Deno.serve(async (req: Request): Promise<Response> => {
  if (req.method === "OPTIONS") {
    return handleOptions();
  }

  if (req.method !== "GET") {
    return jsonResponse({ error: "Method not allowed." }, 405);
  }

  const url = new URL(req.url);
  const teamAbbr = url.searchParams.get("team_abbr");
  const languageCode = url.searchParams.get("language_code");

  if (!teamAbbr) {
    return jsonResponse(
      { error: "Query parameter 'team_abbr' is required." },
      400,
    );
  }

  if (!languageCode) {
    return jsonResponse(
      { error: "Query parameter 'language_code' is required." },
      400,
    );
  }

  // Validate language code
  if (languageCode !== "en" && languageCode !== "de") {
    return jsonResponse(
      {
        error:
          "Query parameter 'language_code' must be either 'en' or 'de'.",
      },
      400,
    );
  }

  try {
    const articles = await fetchTeamArticles(teamAbbr, languageCode);

    return jsonResponse({
      team_abbr: teamAbbr,
      language_code: languageCode,
      count: articles.length,
      articles,
    });
  } catch (error) {
    if (error instanceof HttpError) {
      return jsonResponse({ error: error.message }, error.status);
    }

    console.error("Unexpected error", error);
    return jsonResponse({ error: "Unexpected server error." }, 500);
  }
});
