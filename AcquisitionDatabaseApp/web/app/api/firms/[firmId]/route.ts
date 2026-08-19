import { auth } from "../../../../auth"; import { firmData } from "../../../../lib/queries";
export async function GET(_:Request,{params}:{params:Promise<{firmId:string}>}){if(!(await auth()))return Response.json({error:"Unauthorized"},{status:401});const d=await firmData((await params).firmId);if(!d.firm)return Response.json({error:"Not found"},{status:404});return Response.json(d);}
