FROM node:24-alpine AS builder

WORKDIR /app

COPY package.json yarn.lock ./
RUN yarn install --frozen-lockfile

COPY . .
RUN yarn build


FROM node:24-alpine

WORKDIR /app
ENV NODE_ENV=production
ENV HOST=0.0.0.0
ENV PORT=3000
# Overridden at `docker run`/compose time to point at the deployed backend; the API is public and
# CORS-open (see docs/04), so no reverse proxy is needed to avoid cross-origin issues.
ENV NUXT_PUBLIC_API_BASE=http://localhost:8000

COPY --from=builder /app/.output ./.output

EXPOSE 3000

CMD ["node", ".output/server/index.mjs"]
