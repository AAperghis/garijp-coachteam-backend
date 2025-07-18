# frontend/Dockerfile
FROM node:18 AS builder
WORKDIR /app
COPY . .
RUN npm install && npm run build

FROM node:18
WORKDIR /app
COPY --from=builder /app ./
ENV PORT=3000
ENV BASE_PATH=/myapp
EXPOSE 3000
CMD ["npm", "start"]
