# RAHBAR chat UI. Build context: ui/  (docker build -t rahbar-ui:<tag> ui)
# Static files only, served by nginx on 8080 as a non-root user with a read-only
# root filesystem (section 4.7). ui/nginx.conf already assumes both of these.
FROM nginxinc/nginx-unprivileged:1.27-alpine

# Patch OS packages with known fixed CVEs in the base image (Trivy gate in ci.yml).
USER root
RUN for i in 1 2 3 4 5; do apk upgrade --no-cache && break; sleep 5; done

COPY nginx.conf /etc/nginx/nginx.conf
COPY index.html /usr/share/nginx/html/index.html

USER nginx
EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
