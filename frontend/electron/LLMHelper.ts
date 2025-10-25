import { GoogleGenerativeAI, GenerativeModel } from "@google/generative-ai"
import OpenAI from "openai"
import fs from "fs"
import path from "path"

type Provider = "gemini" | "ollama" | "openai"

interface LLMHelperOptions {
  provider: Provider
  geminiApiKey?: string
  geminiModel?: string
  openaiApiKey?: string
  openaiModel?: string
  ollamaModel?: string
  ollamaUrl?: string
}

interface OllamaResponse {
  response: string
  done: boolean
}

export class LLMHelper {
  private provider: Provider
  private model: GenerativeModel | null = null
  private geminiModelName: string = "gemini-2.0-flash"
  private openaiClient: OpenAI | null = null
  private openaiModel: string = "gpt-4o-mini"
  private readonly systemPrompt = `You are Wingman AI, a helpful, proactive assistant for any kind of problem or situation (not just coding). For any user input, analyze the situation, provide a clear problem statement, relevant context, and suggest several possible responses or actions the user could take next. Always explain your reasoning. Present your suggestions as a list of options or next steps.`
  private useOllama = false
  private ollamaModel: string = "llama3.2"
  private ollamaUrl: string = "http://localhost:11434"

  constructor(options: LLMHelperOptions) {
    this.provider = options.provider
    this.useOllama = options.provider === "ollama"

    if (options.provider === "ollama") {
      this.ollamaUrl = options.ollamaUrl || this.ollamaUrl
      this.ollamaModel = options.ollamaModel || "gemma:latest"
      console.log(`[LLMHelper] Using Ollama with model: ${this.ollamaModel}`)
      void this.initializeOllamaModel()
      return
    }

    if (options.provider === "gemini") {
      const apiKey = options.geminiApiKey
      if (!apiKey) {
        throw new Error("Gemini provider selected but no GEMINI_API_KEY provided")
      }
      const modelName = options.geminiModel || process.env.GEMINI_MODEL || this.geminiModelName
      this.geminiModelName = modelName
      const genAI = new GoogleGenerativeAI(apiKey)
      this.model = genAI.getGenerativeModel({ model: modelName })
      console.log(`[LLMHelper] Using Google Gemini (${modelName})`)
      return
    }

    if (options.provider === "openai") {
      const apiKey = options.openaiApiKey
      if (!apiKey) {
        throw new Error("OpenAI provider selected but no OPENAI_API_KEY provided")
      }
      this.openaiModel = options.openaiModel || process.env.OPENAI_MODEL || "gpt-4o-mini"
      this.openaiClient = new OpenAI({ apiKey })
      console.log(`[LLMHelper] Using OpenAI (${this.openaiModel})`)
      return
    }

    throw new Error(`Unsupported provider: ${options.provider}`)
  }

  private async fileToGenerativePart(imagePath: string) {
    const imageData = await fs.promises.readFile(imagePath)
    return {
      inlineData: {
        data: imageData.toString("base64"),
        mimeType: this.getMimeTypeFromPath(imagePath, "image/png")
      }
    }
  }

  private async fileToOpenAIImagePart(imagePath: string) {
    const imageData = await fs.promises.readFile(imagePath)
    const format = this.getImageFormatFromPath(imagePath)
    return {
      type: "input_image",
      image: {
        data: imageData.toString("base64"),
        format
      },
      detail: "auto"
    } as const
  }

  private getImageFormatFromPath(imagePath: string): "png" | "jpg" | "jpeg" | "webp" {
    const ext = path.extname(imagePath).toLowerCase()
    if (ext === ".png") return "png"
    if (ext === ".jpg") return "jpg"
    if (ext === ".jpeg") return "jpeg"
    if (ext === ".webp") return "webp"
    return "png"
  }

  private getMimeTypeFromPath(filePath: string, fallback: string): string {
    const ext = path.extname(filePath).toLowerCase()
    switch (ext) {
      case ".png":
        return "image/png"
      case ".jpg":
      case ".jpeg":
        return "image/jpeg"
      case ".webp":
        return "image/webp"
      case ".gif":
        return "image/gif"
      case ".mp3":
        return "audio/mpeg"
      case ".wav":
        return "audio/wav"
      case ".m4a":
        return "audio/m4a"
      default:
        return fallback
    }
  }

  private getAudioFormatFromMime(mimeType: string): "mp3" | "wav" | "m4a" | "ogg" | "webm" {
    const subtype = mimeType.split("/")[1]?.toLowerCase() || ""
    if (subtype.includes("mpeg") || subtype.includes("mp3")) return "mp3"
    if (subtype.includes("wav")) return "wav"
    if (subtype.includes("m4a") || subtype.includes("mp4")) return "m4a"
    if (subtype.includes("ogg")) return "ogg"
    if (subtype.includes("webm")) return "webm"
    return "mp3"
  }

  private cleanJsonResponse(text: string): string {
    const withoutFence = text.replace(/^```(?:json)?\n/, "").replace(/\n```$/, "")
    return withoutFence.trim()
  }

  private extractOpenAIText(response: any): string {
    if (!response) {
      throw new Error("Empty OpenAI response")
    }

    if (typeof response.output_text === "string" && response.output_text.trim().length) {
      return response.output_text.trim()
    }

    if (Array.isArray(response.output)) {
      const collected = response.output
        .flatMap((item: any) => item?.content ?? [])
        .filter((content: any) => content?.type === "output_text" && typeof content?.text === "string")
        .map((content: any) => content.text.trim())
        .filter(Boolean)
      if (collected.length > 0) {
        return collected.join("\n").trim()
      }
    }

    if (Array.isArray(response.content)) {
      const collected = response.content
        .filter((item: any) => item?.type === "text" && typeof item?.text === "string")
        .map((item: any) => item.text.trim())
        .filter(Boolean)
      if (collected.length > 0) {
        return collected.join("\n").trim()
      }
    }

    throw new Error("OpenAI response did not include textual output")
  }

  private async callOllama(prompt: string): Promise<string> {
    try {
      const response = await fetch(`${this.ollamaUrl}/api/generate`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          model: this.ollamaModel,
          prompt,
          stream: false,
          options: {
            temperature: 0.7,
            top_p: 0.9
          }
        })
      })

      if (!response.ok) {
        throw new Error(`Ollama API error: ${response.status} ${response.statusText}`)
      }

      const data: OllamaResponse = await response.json()
      return data.response
    } catch (error: any) {
      console.error("[LLMHelper] Error calling Ollama:", error)
      throw new Error(`Failed to connect to Ollama: ${error.message}. Make sure Ollama is running on ${this.ollamaUrl}`)
    }
  }

  private async checkOllamaAvailable(): Promise<boolean> {
    try {
      const response = await fetch(`${this.ollamaUrl}/api/tags`)
      return response.ok
    } catch {
      return false
    }
  }

  private async initializeOllamaModel(): Promise<void> {
    try {
      const availableModels = await this.getOllamaModels()
      if (availableModels.length === 0) {
        console.warn("[LLMHelper] No Ollama models found")
        return
      }

      if (!availableModels.includes(this.ollamaModel)) {
        this.ollamaModel = availableModels[0]
        console.log(`[LLMHelper] Auto-selected first available model: ${this.ollamaModel}`)
      }

      await this.callOllama("Hello")
      console.log(`[LLMHelper] Successfully initialized with model: ${this.ollamaModel}`)
    } catch (error: any) {
      console.error(`[LLMHelper] Failed to initialize Ollama model: ${error.message}`)
      try {
        const models = await this.getOllamaModels()
        if (models.length > 0) {
          this.ollamaModel = models[0]
          console.log(`[LLMHelper] Fallback to: ${this.ollamaModel}`)
        }
      } catch (fallbackError: any) {
        console.error(`[LLMHelper] Fallback also failed: ${fallbackError.message}`)
      }
    }
  }

  private ensureGeminiModel(): GenerativeModel {
    if (!this.model) {
      throw new Error("No Gemini model configured")
    }
    return this.model
  }

  private ensureOpenAIClient(): OpenAI {
    if (!this.openaiClient) {
      throw new Error("No OpenAI client configured")
    }
    return this.openaiClient
  }

  public async extractProblemFromImages(imagePaths: string[]) {
    const prompt = `${this.systemPrompt}\n\nYou are a wingman. Please analyze these images and extract the following information in JSON format:\n{
  "problem_statement": "A clear statement of the problem or situation depicted in the images.",
  "context": "Relevant background or context from the images.",
  "suggested_responses": ["First possible answer or action", "Second possible answer or action", "..."],
  "reasoning": "Explanation of why these suggestions are appropriate."
}\nImportant: Return ONLY the JSON object, without any markdown formatting or code blocks.`

    try {
      if (this.provider === "ollama") {
        throw new Error("Image analysis is not supported in Ollama mode. Switch to OpenAI or Gemini.")
      }

      if (this.provider === "gemini") {
        const imageParts = await Promise.all(imagePaths.map((p) => this.fileToGenerativePart(p)))
        const model = this.ensureGeminiModel()
        const result = await model.generateContent([prompt, ...imageParts])
        const response = await result.response
        const text = this.cleanJsonResponse(response.text())
        return JSON.parse(text)
      }

      const client = this.ensureOpenAIClient()
      const imageParts = await Promise.all(imagePaths.map((p) => this.fileToOpenAIImagePart(p)))
      const result = await client.responses.create({
        model: this.openaiModel,
        input: [
          {
            role: "user",
            content: [{ type: "input_text", text: prompt }, ...imageParts]
          }
        ]
      } as any)
      const text = this.cleanJsonResponse(this.extractOpenAIText(result))
      return JSON.parse(text)
    } catch (error) {
      console.error("Error extracting problem from images:", error)
      throw error
    }
  }

  public async generateSolution(problemInfo: any) {
    const prompt = `${this.systemPrompt}\n\nGiven this problem or situation:\n${JSON.stringify(problemInfo, null, 2)}\n\nPlease provide your response in the following JSON format:\n{
  "solution": {
    "code": "The code or main answer here.",
    "problem_statement": "Restate the problem or situation.",
    "context": "Relevant background/context.",
    "suggested_responses": ["First possible answer or action", "Second possible answer or action", "..."],
    "reasoning": "Explanation of why these suggestions are appropriate."
  }
}\nImportant: Return ONLY the JSON object, without any markdown formatting or code blocks.`

    console.log("[LLMHelper] Calling LLM for solution...")
    try {
      if (this.provider === "ollama") {
        const response = await this.callOllama(prompt)
        const text = this.cleanJsonResponse(response)
        const parsed = JSON.parse(text)
        console.log("[LLMHelper] Parsed LLM response:", parsed)
        return parsed
      }

      if (this.provider === "gemini") {
        const model = this.ensureGeminiModel()
        const result = await model.generateContent(prompt)
        const response = await result.response
        const text = this.cleanJsonResponse(response.text())
        const parsed = JSON.parse(text)
        console.log("[LLMHelper] Parsed LLM response:", parsed)
        return parsed
      }

      const client = this.ensureOpenAIClient()
      const result = await client.responses.create({
        model: this.openaiModel,
        input: [
          {
            role: "user",
            content: [{ type: "input_text", text: prompt }]
          }
        ]
      } as any)
      const text = this.cleanJsonResponse(this.extractOpenAIText(result))
      const parsed = JSON.parse(text)
      console.log("[LLMHelper] Parsed LLM response:", parsed)
      return parsed
    } catch (error) {
      console.error("[LLMHelper] Error in generateSolution:", error)
      throw error
    }
  }

  public async debugSolutionWithImages(problemInfo: any, currentCode: string, debugImagePaths: string[]) {
    const prompt = `${this.systemPrompt}\n\nYou are a wingman. Given:\n1. The original problem or situation: ${JSON.stringify(problemInfo, null, 2)}\n2. The current response or approach: ${currentCode}\n3. The debug information in the provided images\n\nPlease analyze the debug information and provide feedback in this JSON format:\n{
  "solution": {
    "code": "The code or main answer here.",
    "problem_statement": "Restate the problem or situation.",
    "context": "Relevant background/context.",
    "suggested_responses": ["First possible answer or action", "Second possible answer or action", "..."],
    "reasoning": "Explanation of why these suggestions are appropriate."
  }
}\nImportant: Return ONLY the JSON object, without any markdown formatting or code blocks.`

    try {
      if (this.provider === "ollama") {
        throw new Error("Image-based debugging is not supported in Ollama mode. Switch to OpenAI or Gemini.")
      }

      if (this.provider === "gemini") {
        const imageParts = await Promise.all(debugImagePaths.map((p) => this.fileToGenerativePart(p)))
        const model = this.ensureGeminiModel()
        const result = await model.generateContent([prompt, ...imageParts])
        const response = await result.response
        const text = this.cleanJsonResponse(response.text())
        const parsed = JSON.parse(text)
        console.log("[LLMHelper] Parsed debug LLM response:", parsed)
        return parsed
      }

      const client = this.ensureOpenAIClient()
      const imageParts = await Promise.all(debugImagePaths.map((p) => this.fileToOpenAIImagePart(p)))
      const result = await client.responses.create({
        model: this.openaiModel,
        input: [
          {
            role: "user",
            content: [{ type: "input_text", text: prompt }, ...imageParts]
          }
        ]
      } as any)
      const text = this.cleanJsonResponse(this.extractOpenAIText(result))
      const parsed = JSON.parse(text)
      console.log("[LLMHelper] Parsed debug LLM response:", parsed)
      return parsed
    } catch (error) {
      console.error("Error debugging solution with images:", error)
      throw error
    }
  }

  public async analyzeAudioFile(audioPath: string) {
    try {
      const audioData = await fs.promises.readFile(audioPath)
      const mimeType = this.getMimeTypeFromPath(audioPath, "audio/mp3")

      if (this.provider === "ollama") {
        const response = await this.callOllama(`${this.systemPrompt}\n\nDescribe the following audio (base64 encoded): ${audioData.toString("base64")}`)
        return { text: response, timestamp: Date.now() }
      }

      if (this.provider === "gemini") {
        const audioPart = {
          inlineData: {
            data: audioData.toString("base64"),
            mimeType
          }
        }
        const prompt = `${this.systemPrompt}\n\nDescribe this audio clip in a short, concise answer. In addition to your main answer, suggest several possible actions or responses the user could take next based on the audio. Do not return a structured JSON object, just answer naturally as you would to a user.`
        const model = this.ensureGeminiModel()
        const result = await model.generateContent([prompt, audioPart])
        const response = await result.response
        const text = response.text()
        return { text, timestamp: Date.now() }
      }

      const client = this.ensureOpenAIClient()
      const audioFormat = this.getAudioFormatFromMime(mimeType)
      const prompt = `${this.systemPrompt}\n\nDescribe this audio clip in a short, concise answer. In addition to your main answer, suggest several possible actions or responses the user could take next based on the audio. Do not return a structured JSON object, just answer naturally as you would to a user.`
      const result = await client.responses.create({
        model: this.openaiModel,
        input: [
          {
            role: "user",
            content: [
              { type: "input_text", text: prompt },
              {
                type: "input_audio",
                audio: {
                  data: audioData.toString("base64"),
                  format: audioFormat
                }
              }
            ]
          }
        ]
      } as any)
      const text = this.extractOpenAIText(result)
      return { text, timestamp: Date.now() }
    } catch (error) {
      console.error("Error analyzing audio file:", error)
      throw error
    }
  }

  public async analyzeAudioFromBase64(data: string, mimeType: string) {
    try {
      if (this.provider === "ollama") {
        const response = await this.callOllama(`${this.systemPrompt}\n\nDescribe the following audio (base64 encoded): ${data}`)
        return { text: response, timestamp: Date.now() }
      }

      if (this.provider === "gemini") {
        const audioPart = {
          inlineData: {
            data,
            mimeType
          }
        }
        const prompt = `${this.systemPrompt}\n\nDescribe this audio clip in a short, concise answer. In addition to your main answer, suggest several possible actions or responses the user could take next based on the audio. Do not return a structured JSON object, just answer naturally as you would to a user and be concise.`
        const model = this.ensureGeminiModel()
        const result = await model.generateContent([prompt, audioPart])
        const response = await result.response
        const text = response.text()
        return { text, timestamp: Date.now() }
      }

      const client = this.ensureOpenAIClient()
      const audioFormat = this.getAudioFormatFromMime(mimeType)
      const prompt = `${this.systemPrompt}\n\nDescribe this audio clip in a short, concise answer. In addition to your main answer, suggest several possible actions or responses the user could take next based on the audio. Do not return a structured JSON object, just answer naturally as you would to a user and be concise.`
      const result = await client.responses.create({
        model: this.openaiModel,
        input: [
          {
            role: "user",
            content: [
              { type: "input_text", text: prompt },
              {
                type: "input_audio",
                audio: {
                  data,
                  format: audioFormat
                }
              }
            ]
          }
        ]
      } as any)
      const text = this.extractOpenAIText(result)
      return { text, timestamp: Date.now() }
    } catch (error) {
      console.error("Error analyzing audio from base64:", error)
      throw error
    }
  }

  public async analyzeImageFile(imagePath: string) {
    try {
      if (this.provider === "ollama") {
        throw new Error("Image analysis is not supported in Ollama mode. Switch to OpenAI or Gemini.")
      }

      if (this.provider === "gemini") {
        const imageData = await fs.promises.readFile(imagePath)
        const imagePart = {
          inlineData: {
            data: imageData.toString("base64"),
            mimeType: this.getMimeTypeFromPath(imagePath, "image/png")
          }
        }
        const prompt = `${this.systemPrompt}\n\nDescribe the content of this image in a short, concise answer. In addition to your main answer, suggest several possible actions or responses the user could take next based on the image. Do not return a structured JSON object, just answer naturally as you would to a user. Be concise and brief.`
        const model = this.ensureGeminiModel()
        const result = await model.generateContent([prompt, imagePart])
        const response = await result.response
        const text = response.text()
        return { text, timestamp: Date.now() }
      }

      const client = this.ensureOpenAIClient()
      const prompt = `${this.systemPrompt}\n\nDescribe the content of this image in a short, concise answer. In addition to your main answer, suggest several possible actions or responses the user could take next based on the image. Do not return a structured JSON object, just answer naturally as you would to a user. Be concise and brief.`
      const imagePart = await this.fileToOpenAIImagePart(imagePath)
      const result = await client.responses.create({
        model: this.openaiModel,
        input: [
          {
            role: "user",
            content: [{ type: "input_text", text: prompt }, imagePart]
          }
        ]
      } as any)
      const text = this.extractOpenAIText(result)
      return { text, timestamp: Date.now() }
    } catch (error) {
      console.error("Error analyzing image file:", error)
      throw error
    }
  }

  public async chatWithGemini(message: string): Promise<string> {
    try {
      if (this.provider === "ollama") {
        return this.callOllama(message)
      }

      if (this.provider === "gemini") {
        const model = this.ensureGeminiModel()
        const result = await model.generateContent(message)
        const response = await result.response
        return response.text()
      }

      const client = this.ensureOpenAIClient()
      const result = await client.responses.create({
        model: this.openaiModel,
        input: [
          {
            role: "user",
            content: [{ type: "input_text", text: `${this.systemPrompt}\n\n${message}` }]
          }
        ]
      } as any)
      return this.extractOpenAIText(result)
    } catch (error) {
      console.error("[LLMHelper] Error in chatWithGemini:", error)
      throw error
    }
  }

  public async chat(message: string): Promise<string> {
    return this.chatWithGemini(message)
  }

  public isUsingOllama(): boolean {
    return this.useOllama
  }

  public async getOllamaModels(): Promise<string[]> {
    if (!this.useOllama) return []

    try {
      const response = await fetch(`${this.ollamaUrl}/api/tags`)
      if (!response.ok) throw new Error("Failed to fetch models")

      const data = await response.json()
      return data.models?.map((model: any) => model.name) || []
    } catch (error) {
      console.error("[LLMHelper] Error fetching Ollama models:", error)
      return []
    }
  }

  public getCurrentProvider(): Provider {
    return this.provider
  }

  public getCurrentModel(): string {
    if (this.provider === "ollama") return this.ollamaModel
    if (this.provider === "gemini") return this.geminiModelName
    return this.openaiModel
  }

  public async switchToOllama(model?: string, url?: string): Promise<void> {
    this.provider = "ollama"
    this.useOllama = true
    if (url) this.ollamaUrl = url
    if (model) {
      this.ollamaModel = model
    } else {
      await this.initializeOllamaModel()
    }
    console.log(`[LLMHelper] Switched to Ollama: ${this.ollamaModel} at ${this.ollamaUrl}`)
  }

  public async switchToGemini(apiKey?: string, modelName?: string): Promise<void> {
    const key = apiKey || process.env.GEMINI_API_KEY
    if (!key && !this.model) {
      throw new Error("No Gemini API key provided and no existing model instance")
    }
    if (key) {
      const modelId = modelName || process.env.GEMINI_MODEL || "gemini-2.0-flash"
      this.geminiModelName = modelId
      const genAI = new GoogleGenerativeAI(key)
      this.model = genAI.getGenerativeModel({ model: modelId })
    }
    this.provider = "gemini"
    this.useOllama = false
    console.log("[LLMHelper] Switched to Gemini")
  }

  public async switchToOpenAI(apiKey?: string, modelName?: string): Promise<void> {
    const key = apiKey || process.env.OPENAI_API_KEY
    if (!key && !this.openaiClient) {
      throw new Error("No OpenAI API key provided and no existing client instance")
    }
    if (key) {
      this.openaiClient = new OpenAI({ apiKey: key })
    }
    if (modelName || process.env.OPENAI_MODEL) {
      this.openaiModel = modelName || process.env.OPENAI_MODEL || this.openaiModel
    }
    this.provider = "openai"
    this.useOllama = false
    console.log(`[LLMHelper] Switched to OpenAI (${this.openaiModel})`)
  }

  public async testConnection(): Promise<{ success: boolean; error?: string }> {
    try {
      if (this.provider === "ollama") {
        const available = await this.checkOllamaAvailable()
        if (!available) {
          return { success: false, error: `Ollama not available at ${this.ollamaUrl}` }
        }
        await this.callOllama("Hello")
        return { success: true }
      }

      if (this.provider === "gemini") {
        if (!this.model) {
          return { success: false, error: "No Gemini model configured" }
        }
        const result = await this.model.generateContent("Hello")
        const response = await result.response
        const text = response.text()
        return text ? { success: true } : { success: false, error: "Empty response from Gemini" }
      }

      const client = this.ensureOpenAIClient()
      const result = await client.responses.create({
        model: this.openaiModel,
        input: [
          {
            role: "user",
            content: [{ type: "input_text", text: "Hello" }]
          }
        ]
      } as any)
      const text = this.extractOpenAIText(result)
      return text ? { success: true } : { success: false, error: "Empty response from OpenAI" }
    } catch (error: any) {
      return { success: false, error: error.message }
    }
  }
}
