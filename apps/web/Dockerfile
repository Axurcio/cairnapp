# syntax=docker/dockerfile:1.7
# Cairn website: static build served by nginx, which also proxies /v1 to the API so the
# site and API share one origin (the session cookie needs no CORS). Build context: apps/web.

FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY . .
# "true" lists the SYNTHETIC demo accounts on the sign-in page. Local stacks only.
ARG VITE_DEMO_ACCOUNTS=false
ENV VITE_DEMO_ACCOUNTS=${VITE_DEMO_ACCOUNTS}
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.29-alpine AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
