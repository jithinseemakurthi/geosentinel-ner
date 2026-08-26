FROM node:20-alpine

WORKDIR /app

COPY package.json yarn.lock* ./
RUN npm install --omit=dev

COPY . .

ENV PORT=9090
EXPOSE 9090

CMD ["npm", "start"]
