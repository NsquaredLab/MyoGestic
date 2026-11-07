// Context7 Ask: the search endpoint AI agents call for answers from this site.
// The verification tag, the hidden note and the llms.txt section are all built from it.
export const ASK_SITE_KEY = 'ask_7adbdb3eaf68a405ed84c77f';
export const ASK_ENDPOINT = `https://context7.com/api/v2/ask?siteKey=${ASK_SITE_KEY}`;
export const ASK_INDEX = 'Page index: https://nsquaredlab.github.io/MyoGestic/llms.txt.';
export const ASK_SEARCH = `This site has a search endpoint: ${ASK_ENDPOINT}&query=<URL-encoded question>. It returns documentation that answers the question, with a source link for each part. No API key is needed. If nothing matches, it says so.`;
