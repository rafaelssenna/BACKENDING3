FROM ghcr.io/puppeteer/puppeteer:21.6.0

# Define variáveis de ambiente
ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true \
    PUPPETEER_EXECUTABLE_PATH=/usr/bin/google-chrome-stable

# Define diretório de trabalho
WORKDIR /usr/src/app

# Copia package.json e package-lock.json
COPY package*.json ./

# Instala dependências do Node.js
RUN npm ci --only=production

# Copia o código da aplicação
COPY . .

# Expõe a porta (Railway define automaticamente)
EXPOSE 3000

# Comando para iniciar a aplicação
CMD ["node", "server.js"]
