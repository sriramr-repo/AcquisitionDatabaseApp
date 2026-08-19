import { auth } from "../../../auth"; import { dashboardData } from "../../../lib/queries";
export async function GET(){if(!(await auth()))return Response.json({error:"Unauthorized"},{status:401});return Response.json(await dashboardData());}
