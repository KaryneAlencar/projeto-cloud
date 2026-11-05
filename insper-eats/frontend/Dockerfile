FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_CHAT_MODE=api
ARG VITE_CHAT_API_URL=/api
ENV VITE_CHAT_MODE=$VITE_CHAT_MODE VITE_CHAT_API_URL=$VITE_CHAT_API_URL
RUN npm run build

FROM nginxinc/nginx-unprivileged:stable-alpine
ENV CHAT_UPSTREAM=http://chat:8001
COPY --chmod=755 nginx/15-app-dns.envsh /docker-entrypoint.d/15-app-dns.envsh
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
