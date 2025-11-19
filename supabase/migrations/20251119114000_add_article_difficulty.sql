-- Add article_difficulty column to news_urls
ALTER TABLE news_urls
    ADD COLUMN IF NOT EXISTS article_difficulty TEXT;
