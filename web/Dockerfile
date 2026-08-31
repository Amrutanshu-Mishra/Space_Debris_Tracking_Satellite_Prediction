# web — multi-stage. Stage 1 (node) builds the static bundle; stage 2 (nginx)
# serves it on :80 and proxies /api to the api service so the browser makes
# same-origin requests (no CORS in this deployment). The bundle carries its
# own fonts, CSS, and the ground-track world outline — nothing is fetched at
# runtime.

FROM node:20-alpine AS build
WORKDIR /app

# deps first, for layer caching (package-lock.json is optional)
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund

COPY . .

# same-origin: the client calls /api/v1 and nginx proxies it to `api`
ENV VITE_API_BASE_URL=/api/v1 \
    VITE_WS_BASE_URL=/api/v1
RUN npm run build

FROM nginx:1.27-alpine
RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/prahari.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
# nginx:alpine's base image already runs nginx in the foreground
