const SMTP_TRANSPORT = {
  host: process.env.TEXTBELT_SMTP_HOST || 'smtp.gmail.com',
  port: Number(process.env.TEXTBELT_SMTP_PORT || 587),
  auth: {
    user: process.env.TEXTBELT_SMTP_USER,
    pass: process.env.TEXTBELT_SMTP_PASS,
  },
  secure: false,
};

module.exports = {
  transport: SMTP_TRANSPORT,
  mailOptions: {
    from: `"${process.env.TEXTBELT_FROM_NAME || 'GeoSentinel-NER'}" <${process.env.TEXTBELT_FROM_ADDRESS || process.env.TEXTBELT_SMTP_USER}>`,
  },
  debugEnabled: process.env.TEXTBELT_DEBUG === 'true',
};
