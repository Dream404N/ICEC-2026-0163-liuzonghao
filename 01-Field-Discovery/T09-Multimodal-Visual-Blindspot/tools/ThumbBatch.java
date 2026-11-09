import java.awt.*;
import java.awt.image.*;
import java.io.*;
import java.util.*;
import javax.imageio.*;
import javax.imageio.stream.*;

/**
 * 无第三方依赖的批量缩略图生成器（JDK 11+ 单文件源码启动）。
 *
 * 为什么要这一层：课题 09 的现场原图是 5712x4284 / 5~13MB，直接以 base64
 * 塞进 VLM 请求既可能撞网关体积上限，也会按原分辨率切成巨额视觉 token。
 * 统一缩到最长边 N 像素后再送模型，既控制成本，也保证四个模型看到的是
 * 完全相同的输入（对比实验的控制变量）。
 *
 * 用法: java ThumbBatch.java <源目录> <输出目录> <最长边> <JPEG质量0~1>
 * 不依赖 Pillow / ImageMagick / ffmpeg，Windows + JDK 即可跑。
 */
public class ThumbBatch {
    public static void main(String[] args) throws Exception {
        File srcDir = new File(args[0]);
        File outDir = new File(args[1]);
        int maxEdge = Integer.parseInt(args[2]);
        float quality = Float.parseFloat(args[3]);
        outDir.mkdirs();

        File[] files = srcDir.listFiles((d, n) -> {
            String s = n.toLowerCase(Locale.ROOT);
            return s.endsWith(".jpg") || s.endsWith(".jpeg") || s.endsWith(".png");
        });
        if (files == null || files.length == 0) {
            System.out.println("NO_IMAGE_IN " + srcDir);
            return;
        }
        Arrays.sort(files);
        ImageWriter writer = ImageIO.getImageWritersByFormatName("jpeg").next();
        ImageWriteParam param = writer.getDefaultWriteParam();
        param.setCompressionMode(ImageWriteParam.MODE_EXPLICIT);
        param.setCompressionQuality(quality);

        for (File src : files) {
            BufferedImage im = ImageIO.read(src);
            if (im == null) { System.out.println("SKIP_UNREADABLE " + src.getName()); continue; }
            int w = im.getWidth(), h = im.getHeight();
            double scale = Math.min(1.0, (double) maxEdge / Math.max(w, h));
            int nw = Math.max(1, (int) (w * scale)), nh = Math.max(1, (int) (h * scale));
            BufferedImage bi = new BufferedImage(nw, nh, BufferedImage.TYPE_INT_RGB);
            Graphics2D g = bi.createGraphics();
            g.setRenderingHint(RenderingHints.KEY_INTERPOLATION,
                    RenderingHints.VALUE_INTERPOLATION_BICUBIC);
            g.drawImage(im, 0, 0, nw, nh, null);
            g.dispose();

            String base = src.getName().replaceFirst("\\.[^.]+$", "");
            File out = new File(outDir, base + ".jpg");
            try (ImageOutputStream ios = ImageIO.createImageOutputStream(out)) {
                writer.setOutput(ios);
                writer.write(null, new IIOImage(bi, null, null), param);
            }
            System.out.println(src.getName() + " " + w + "x" + h + " -> " + nw + "x" + nh
                    + " " + out.length() + "B");
        }
        writer.dispose();
    }
}
