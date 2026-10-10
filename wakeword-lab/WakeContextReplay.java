import com.example.emilyapp.*;
import java.io.*;
import java.util.*;

/** Runs the Android Kotlin policy against local PCM; no recording or network. */
public class WakeContextReplay {
    public static void main(String[] args) throws Exception {
        try (DataInputStream input = new DataInputStream(new BufferedInputStream(new FileInputStream(args[0])))) {
            int cases = input.readInt();
            for (int c=0;c<cases;c++) {
                String id=input.readUTF();boolean positive=input.readBoolean();
                short[] pcm=new short[input.readInt()];for(int i=0;i<pcm.length;i++)pcm[i]=input.readShort();
                int candidates=input.readInt();
                List<List<WakeWordCandidateEvaluator.Word>> words=new ArrayList<>();
                double[] endpoints=new double[candidates];
                for(int j=0;j<candidates;j++){
                    List<WakeWordCandidateEvaluator.Word> ws=new ArrayList<>();int n=input.readInt();
                    for(int k=0;k<n;k++)ws.add(new WakeWordCandidateEvaluator.Word(input.readUTF(),input.readFloat(),input.readDouble(),input.readDouble()));
                    words.add(ws);endpoints[j]=input.readDouble();
                }
                WakeSpeechContext context=new WakeSpeechContext(16000);int cursor=0;
                for(int j=0;j<candidates;j++){
                    List<WakeWordCandidateEvaluator.Word> ws=words.get(j);
                    Object decision=WakeWordCandidateEvaluator.INSTANCE.evaluate(ws,.70f,.18,null,.65,3,false);
                    if(!(decision instanceof WakeWordCandidateEvaluator.Result.Accepted))continue;
                    double end=ws.get(ws.size()-1).getEndSeconds();
                    int until=Math.min(pcm.length,(int)(Math.max(end+.60,endpoints[j])*16000)+320);
                    while(cursor<until){int n=Math.min(320,until-cursor);context.accept(Arrays.copyOfRange(pcm,cursor,cursor+n),n);cursor+=n;}
                    System.out.println(id+"\t"+positive+"\t"+j+"\t"+context.evaluate(ws)+"\t"+Math.max(0,end+.60-endpoints[j]));
                }
            }
        }
    }
}
