-- Changing an existing table: a NEW migration, never an edit to 002.
-- Stores the RAG answer check (0-1, how well the answer is supported by the PDF).
-- NULL when the answer didn't use the documents.
ALTER TABLE messages ADD COLUMN groundedness REAL;
