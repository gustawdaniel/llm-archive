# Stage 1: Build
FROM node:22-alpine AS builder

WORKDIR /app

# BASE_PATH jest wczytywany przez svelte.config.js w czasie BUDOWANIA,
# więc musi być znany tutaj — nie wystarczy zmienna w runtime kontenera.
ARG BASE_PATH=/llm-archive
ENV BASE_PATH=${BASE_PATH}

RUN npm install -g pnpm

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .
RUN pnpm run build
RUN CI=true pnpm prune --prod

# Stage 2: Runner
FROM node:22-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3001
ENV HOST=0.0.0.0
ENV LLM_API_URL=http://127.0.0.1:8080

COPY --from=builder /app/package*.json ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/build ./build

EXPOSE 3001

USER node

CMD ["node", "build/index.js"]
