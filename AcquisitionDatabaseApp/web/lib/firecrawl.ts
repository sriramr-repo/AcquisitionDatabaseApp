import crypto from "node:crypto";
import { db } from "./db";
import { sql } from "drizzle-orm";

export async function scrapeOfficialSite(firmId:string, datasetVersion:string, url:string, requestedBy:string){
  const jobId=crypto.randomUUID(); const now=new Date();
  await db.execute(sql`insert into enrichment_jobs (job_id,firm_id,dataset_version,status,requested_by,created_at) values (${jobId},${firmId},${datasetVersion},'RUNNING',${requestedBy},${now})`);
  if(!process.env.FIRECRAWL_API_KEY){await db.execute(sql`update enrichment_jobs set status='UNAVAILABLE',error_message='FIRECRAWL_API_KEY is not configured',completed_at=${new Date()} where job_id=${jobId}`);return {jobId,status:"UNAVAILABLE"};}
  try{
    const response=await fetch("https://api.firecrawl.dev/v2/scrape",{method:"POST",headers:{Authorization:`Bearer ${process.env.FIRECRAWL_API_KEY}`,"Content-Type":"application/json"},body:JSON.stringify({url,formats:["markdown","links","summary"],onlyMainContent:true,maxAge:172800000})});
    if(!response.ok) throw new Error(`Firecrawl HTTP ${response.status}`);
    const payload:any=await response.json(); const data=payload.data||payload; const markdown=data.markdown||""; const metadata=data.metadata||{}; const scrapeId=metadata.scrapeId||payload.id||null; const sourceId=`firecrawl:${jobId}`;
    const hash=crypto.createHash("sha256").update(markdown).digest("hex");
    await db.execute(sql`insert into research_sources (source_id,firm_id,dataset_version,source_type,source_url,source_title,source_authority,accessed_at,retrieval_status,content_hash,field_supported,source_notes,created_at,updated_at) values (${sourceId},${firmId},${datasetVersion},'official_website',${url},${metadata.title||url},'Firm',${now},'REVIEW_REQUIRED',${hash},'candidate_research_observations',${JSON.stringify({scrapeId,statusCode:metadata.statusCode,contentType:metadata.contentType})},${now},${now}) on conflict (source_id) do nothing`);
    await db.execute(sql`insert into research_evidence_captures (capture_id,source_id,scrape_id,extraction_method,content_type,content,metadata,content_hash,created_at,updated_at) values (${jobId},${sourceId},${scrapeId},'firecrawl_scrape','text/markdown',${markdown},${JSON.stringify(metadata)},${hash},${now},${now}) on conflict (capture_id) do nothing`);
    await db.execute(sql`update enrichment_jobs set status='REVIEW_REQUIRED',completed_at=${new Date()} where job_id=${jobId}`); return {jobId,status:"REVIEW_REQUIRED",sourceId};
  }catch(error){const message=error instanceof Error?error.message:"Firecrawl request failed"; await db.execute(sql`update enrichment_jobs set status='FAILED',error_message=${message},completed_at=${new Date()} where job_id=${jobId}`);return {jobId,status:"FAILED",error:message};}
}
