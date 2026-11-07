# RAHBAR chat UI. Build context: ui/  (docker build -t rahbar-ui:<tag> ui)
# Static files only, served by nginx on 8080 as a non-root user with a read-only
# root filesystem (section 4.7). ui/nginx.conf already assumes both of these.
FROM nginxinc/nginx-unprivileged:1.27-alpine

COPY nginx.conf /etc/nginx/nginx.conf
COPY index.html /usr/share/nginx/html/index.html

USER nginx
EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
